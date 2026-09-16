"""collect_sku_stock against a fake variation picker that behaves like Shopee's:
clicking a selected option deselects it, sold-out options/combinations are
disabled, and the count is shown only once every group is selected."""
from __future__ import annotations

import json
import os

import pytest

from ecommerce.ingestion import browser as B
from ecommerce.platforms.shopee.extract.sku_stock import collect_sku_stock

pytestmark = pytest.mark.skipif(not os.environ.get("ECOMMERCE_CHROME_EXECUTABLE"),
                                reason="set ECOMMERCE_CHROME_EXECUTABLE to run")

COLORS = ["Hồng cá tính", "Trắng đen", "Xanh bầu trời"]
SIZES = ["500ml", "750ml"]
# (color, size) -> stock ; "Hồng cá tính" is fully sold out, (Xanh, 750ml) too
STOCK = {(0, 0): 0, (0, 1): 0, (1, 0): 7, (1, 1): 12, (2, 0): 2, (2, 1): 0}
ITEM = {"tier_variations": [{"name": "Màu Sắc", "options": COLORS}, {"name": "Size", "options": SIZES}],
        "models": [{"model_id": 100 + c * 10 + s, "extinfo": {"tier_index": [c, s]}} for (c, s) in STOCK]}

PAGE = """<html><head><meta charset="utf-8"></head><body>
<div id="g0"></div><div id="g1"></div><div id="q">99 pieces available</div>
<script>
const OPTS = [{}, {}]; const STOCK = {}; let sel = [null, null];
function stock(c, s) {{ return STOCK[c + ',' + s]; }}
function render() {{
  for (let t = 0; t < 2; t++) {{
    const g = document.getElementById('g' + t); g.innerHTML = '';
    OPTS[t].forEach((o, i) => {{
      const b = document.createElement('button'); b.textContent = o; b.setAttribute('aria-label', o);
      // disabled when every compatible combination is sold out
      const other = sel[1 - t];
      const combos = (other === null ? [0, 1, 2].slice(0, OPTS[1 - t].length) : [other])
          .map(j => t === 0 ? stock(i, j) : stock(j, i));
      b.disabled = combos.every(v => v === 0);
      b.onclick = () => {{ sel[t] = (sel[t] === i ? null : i); setTimeout(render, 120); }};
      g.appendChild(b);
    }});
  }}
  document.getElementById('q').textContent =
      (sel[0] !== null && sel[1] !== null ? stock(sel[0], sel[1]) : 99) + ' pieces available';
}}
render();
</script></body></html>""".format(json.dumps(COLORS), json.dumps(SIZES),
                            json.dumps({f"{c},{s}": v for (c, s), v in STOCK.items()}))


def test_collect_reads_every_combination(tmp_path, fast_timeouts):
    with B.open_context(tmp_path / "p", headless=True) as ctx:
        page = ctx.new_page()
        page.set_content(PAGE)
        result = collect_sku_stock(page, ITEM, max_clicks=50, settle_ms=800, timeouts=fast_timeouts)
    got = {int(k): v["available"] for k, v in result["by_model"].items()}
    assert got == {100: 0, 101: 0, 110: 7, 111: 12, 120: 2, 121: 0}
    assert result["complete"] is True
    assert result["baseline"] == 99
    # only changed options are clicked (clicking a selected one would deselect it)
    assert result["clicks"] <= 8


def test_sold_out_combinations_cost_no_click(tmp_path, fast_timeouts):
    """Measured 13/09 on real data: the 26% of SKUs that are sold out already cost
    no click (button disabled -> recorded as 0 directly). This test pins that
    property so it is not 'optimised' away by mistake."""
    with B.open_context(tmp_path / "p", headless=True) as ctx:
        page = ctx.new_page()
        page.set_content(PAGE)
        result = collect_sku_stock(page, ITEM, max_clicks=50, settle_ms=800, timeouts=fast_timeouts)
    sold_out = [k for k, v in result["by_model"].items() if v["available"] == 0]
    assert len(sold_out) == 3                                  # 100, 101, 121
    assert all(result["by_model"][k].get("source") is None for k in sold_out)   # never clicked
    assert result["clicks"] <= len(result["by_model"])          # <= 1 click per SKU


def test_click_cap_stops_early(tmp_path, fast_timeouts):
    with B.open_context(tmp_path / "p", headless=True) as ctx:
        page = ctx.new_page()
        page.set_content(PAGE)
        result = collect_sku_stock(page, ITEM, max_clicks=2, settle_ms=500, timeouts=fast_timeouts)
    assert result["complete"] is False
    assert "giới hạn 2" in result["notes"][0]


PAGE_API = PAGE.replace(
    "  document.getElementById('q').textContent =",
    "  if (sel[0] !== null && sel[1] !== null) fetch('/api/v4/pdp/cart_panel/select_variation_pc?c=' + sel[0] + '&s=' + sel[1], {method: 'POST'});\n"
    "  document.getElementById('q').textContent =")


def test_api_is_preferred_and_brings_voucher_price(tmp_path, fast_timeouts):
    def handle(route):
        if "select_variation" not in route.request.url:        # the product page itself
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=PAGE_API)
            return
        q = dict(p.split("=") for p in route.request.url.split("?")[1].split("&"))
        c, s = int(q["c"]), int(q["s"])
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"error": None, "data": {
            "stock": STOCK[(c, s)],
            "product_price": {"price": {"single_value": (100_000 + c * 1000) * 100_000},
                              "final_price_info": {"model_id": 100 + c * 10 + s}}}}))

    with B.open_context(tmp_path / "p", headless=True) as ctx:
        page = ctx.new_page()
        page.route("http://shop.test/**", handle)       # relative fetch() needs a real origin
        tap = B.ResponseTap(page, ("/pdp/cart_panel/select_variation",))
        page.goto("http://shop.test/product/9/42")
        result = collect_sku_stock(page, ITEM, max_clicks=50, settle_ms=1500, tap=tap, timeouts=fast_timeouts)
    by = {int(k): v for k, v in result["by_model"].items()}
    assert by[110]["available"] == 7 and by[110]["source"] == "api"
    assert by[120]["available"] == 2 and by[120]["final_price"] == 102_000
    assert by[100]["status"] == "Hết hàng"                       # disabled, never clicked
    assert not [n for n in result["notes"] if "≠" in n]           # API and screen agree
