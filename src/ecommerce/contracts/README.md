# contracts/ — data contracts

The tool does not read the web UI; it reads the **JSON** Shopee / TikTok return themselves. Both
platforms can change that JSON at any time without notice. This folder records:

> **Which fields the tool needs, and where it takes them from** — and checks whether the saved
> data still matches.

A real example: on the Shopee search page the `item_basic` block is now always empty and the data
moved to `item_data`. The tool kept working because the reader has a fallback source, and the rule
in `shopee.py` lists both places.

---

## When it speaks up

| When | What runs | What you see |
|---|---|---|
| **While crawling** | `guard.py` checks every file as soon as it is saved | 3 products in a row missing a core field → the tool **stops**, prints the field names and waits for Enter (the 3 is `contracts.guard_streak` in `config/crawl_scope.yaml`) |
| **Any time** | `ecommerce check-schema --platform shopee` | A ✅ / ⚠️ / ❌ table per field, and lines like *"gone X → possibly renamed to Y"* |

`check-schema` only reads saved files and **sends no requests** — it is safe to run during a crawl.
With any ❌ the command exits with code 1 (usable in automation).

---

## Which file to read first

| File | What it does | When to edit |
|---|---|---|
| **`shopee.py`, `tiktok.py`** | **The rule tables.** One rule = one thing the Excel file needs | **When a platform changes its JSON, or when adding an Excel column** |
| `rules.py` | The "language" rules are written in (`Expect`) and how one file is checked | Rarely |
| `paths.py` | Reads values by path, e.g. `pdp.data.item.models[].price` | Rarely |
| `snapshot.py` | Snapshots the **whole** JSON structure, diffs it with the baseline, suggests new names | Rarely |
| `check.py` | Checks a whole crawl run and prints the report (command `check-schema`) | Rarely |
| `guard.py` | Checks while crawling, stops after N broken files in a row | Rarely |
| `baselines/*.json` | The structure of a crawl **known to be good** (the baseline to compare with) | Regenerate with the command, never by hand |

This folder **only reads raw JSON**: it never touches the browser, and `transform/` does not depend
on it. To reuse it in another scraper, move the whole folder.

---

## What a rule looks like

```python
Expect(name="Giá bán", level=CORE, kind=NUMBER, positive=True, feeds=["price_min", "price_max"],
       sources=["pdp.data.item.price_min", "pdp.data.item.price_max", ...,
                "pdp.data.item.models[].price", ...],
       note="price._list_price(). Unit VND x 100000; -1 = not set.")
```

| Field | Meaning |
|---|---|
| `name` | The name shown in reports |
| `sources` | Every place the reader may take it from, **in the order the reader tries them**. One place with data is enough |
| `level` | How bad it is when missing (table below) |
| `kind` | Expected type: `text`, `number`, `list`, `dict`, `bool`, `any` |
| `feeds` | Which columns of `Product.to_row()` this rule fills — used by the sync tests |
| `positive` | Numbers ≤ 0 count as absent (Shopee writes `-1` = "not set") |
| `also` | A source that cannot be written as a path (e.g. the "Thương hiệu" row of the attribute table) |
| `note` | **The matching reader in `transform/`** + remarks for the next person |

### The three levels

| Level | Meaning | When missing |
|---|---|---|
| `CORE` | Every product must have it: name, price, sold, variants | The product counts as **broken**; the guard counts it; check-schema ❌ |
| `IMPORTANT` | Most products have it | ❌ when coverage drops more than 20 points below the baseline |
| `OPTIONAL` | Often empty by nature (video, brand...) | ⚠️ when it drops sharply below the baseline |

---

## When `check-schema` reports ❌ — what to do

1. Read the line *"gone `...` → possibly renamed to `...`"*.
2. Look at one raw file to be sure: `ecommerce inspect SHOPID_ITEMID --depth 3`.
3. Open the ❌ rule in `shopee.py` / `tiktok.py`. Its `note` names the reader in `transform/` → fix that function.
4. Add the new path to the rule's `sources`, **in the order the reader tries them**.
5. `pytest tests/test_contracts.py` → the sync tests report immediately if the rule and the reader disagree.
6. `ecommerce export` → **no need to crawl again**, the raw files already hold the full JSON.
7. Once a new crawl has run well: `ecommerce check-schema --save-baseline`, then commit `baselines/`.

## Adding a new Excel column

1. Write the reader in `transform/<platform>/`.
2. Add an `Expect` to the rule table with `feeds` = the new key in `Product.to_row()`.
3. `pytest tests/test_contracts.py` → the two sync tests run for the new rule automatically.
4. Regenerate the baseline (`--save-baseline`) so the new rule has numbers to compare with.

## The sync tests (`tests/test_contracts.py`) — why rules cannot drift from the code

- **Delete every source of a rule** → the Excel column it feeds must be empty.
  If it still has a value: the reader uses a place the rule does not list → false alarms.
- **Keep only one source** → the Excel column must still have a value.
  If it is empty: the rule lists a place the reader does not use → missed alarms when the platform changes.

These two tests caught real bugs while being written: the "Giá bán" rule was missing `price_max`,
and the TikTok stock rule listed a field that does not yield a number.

---

## Baselines (`baselines/`)

Each file is the structure of one good crawl: the coverage of every rule, and every JSON path with
its type and the share of files that have it. **No product data** — only field names. The current
baselines come from 40 products + 5 search pages per platform (see `made_from` in the file).

Regenerate when: a platform change has just been fixed, or a larger crawl has been checked and is good.

## Path syntax

| Written | Meaning |
|---|---|
| `pdp.data.item.title` | one value |
| `pdp.data.item.models[].price` | the price of **every** element of the list |
| `skus_price.*.sale_price_decimal` | every value of a dict whose keys are ids |
| `rating_count.0` | element 0 of the list |
| `pdp.data.**.attrs` | the key `attrs` at any depth below (like `deep_find`) |

## Why not check the whole JSON

Every Shopee product has hundreds of fields and the platform adds / removes them all the time.
Checking everything would alarm every day. The rules keep only the ~25 fields the tool really
reads; `snapshot.py` still looks at everything, but only to **suggest new names**, never to fail.
