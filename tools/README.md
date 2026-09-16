# tools/ — manual helpers, not part of the main tool

Nothing in `src/ecommerce/` imports from here. Delete the whole folder and crawl / export still run.

| File | What it does |
|---|---|
| `verify_excel_output.py` | Verifies an exported Excel file: 7 automatic checks + a manual check sheet |

```powershell
python tools\verify_excel_output.py output\shopee\giu_nhiet_*.xlsx --sample 10
```

Sends no request to the platforms. Checks: keys and row count, referential integrity, value ranges,
cross consistency, column coverage, IQR outliers, comparison with the original JSON. Exits with a
non-zero code on errors, so it can be wired into CI.

`--sample 10` writes `manual_check_<file>.csv`: 10 top / middle / bottom products to compare by hand
with the website. Fill in the "on site" columns, then mark y/n.
