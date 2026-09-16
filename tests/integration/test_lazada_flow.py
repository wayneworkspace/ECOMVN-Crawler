"""Lazada crawler against a fake lazada.vn served through route interception:
the search endpoint answers JSON with `ajax=true`, product pages are HTML with
`window.__moduleData__ = {...};` (plus a trailing script, quotes and braces in
strings, to exercise the brace scanner), one page is a 'punish' captcha until
the person solves it, one product is a 404, and a re-run fetches nothing again.

    ECOMMERCE_CHROME_EXECUTABLE=/path/to/chrome pytest tests/integration
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from ecommerce.ingestion import browser as B
from ecommerce.ingestion.raw_store import RunStore, read_json
from ecommerce.platforms.lazada.extract import crawl as C
from ecommerce.platforms.lazada.extract import fetch as F
from helpers import PROFILE_OIL, make_cfg

CHROME = os.environ.get("ECOMMERCE_CHROME_EXECUTABLE")
pytestmark = pytest.mark.skipif(not CHROME, reason="set ECOMMERCE_CHROME_EXECUTABLE to run")

FIX = Path(__file__).parents[1] / "fixtures"
STATE = {"solved": False, "requests": []}


def card(item_id: str, name: str, sold: int, ad: bool = False) -> dict:
    return {"itemId": item_id, "skuId": item_id + "0", "sellerId": "77", "name": name, "price": "150000",
            "itemSoldCntShow": f"Đã bán {sold}", "ratingScore": "4.7", "review": "12", "isSponsored": ad,
            "itemUrl": f"//www.lazada.vn/products/x-i{item_id}-s{item_id}0.html"}


def search_json(page: int) -> dict:
    if page == 1:
        items = [card("11", "Nhớt Motul 7100 10W40 1L", 900), card("12", "Lọc nhớt Honda", 800),
                 card("13", "Nhớt Castrol Power1 10W40 0.8L", 700), card("14", "Nhớt Shell AX7 10W40 1L", 600, ad=True)]
    elif page == 2:
        items = [card("15", "Nhớt Liqui Moly Street 10W40 1L", 500), card("16", "Nhớt Repsol Moto 4T 1L", 400)]
    else:
        items = []
    return {"mainInfo": {"totalResults": "6"}, "mods": {"listItems": items}}


def product_html(item_id: str) -> str:
    raw = json.loads((FIX / "lazada_pdp_raw.json").read_text(encoding="utf-8"))
    module = raw["module_data"]
    fields = module["data"]["root"]["fields"]
    fields["primaryKey"] = {"itemId": item_id, "skuId": item_id + "0"}
    fields["product"]["title"] = f"Nhớt mẫu {item_id} 10W-40 1L {{đặc biệt}} \"chính hãng\""   # braces + quotes in strings
    fields["product"]["soldCount"] = str(int(item_id) * 11)
    data = json.dumps(module, ensure_ascii=False)
    tracking = json.dumps({"pdt_item_id": item_id, "pdt_name": "a } b"})
    return (f"<!doctype html><html><head><title>Nhớt mẫu {item_id} | Lazada.vn</title></head><body>"
            f"<script>window.__moduleData__ = {data};\nwindow.other = {{a: 1}};</script>"
            f"<script>window.pdpTrackingData = {tracking};</script></body></html>")


PUNISH = "<!doctype html><html><head><title>Lazada</title></head><body>x5secdata slide to verify</body></html>"
NOT_FOUND = "<!doctype html><html><head><title>404 Not Found</title></head><body>404</body></html>"


def handle(route):
    url = urlparse(route.request.url)
    STATE["requests"].append(url.path + ("?" + url.query if url.query else ""))
    if url.path == "/catalog/":
        q = parse_qs(url.query)
        page = int(q.get("page", ["1"])[0])
        if page == 2 and not STATE["solved"]:
            return route.fulfill(status=200, content_type="text/html", body=PUNISH)
        if "ajax" in q:
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(search_json(page)))
        return route.fulfill(status=200, content_type="text/html", body="<html><title>Lazada</title>ok</html>")
    m = re.match(r"^/products/.*-i(\d+)-s\d+\.html$", url.path)
    if m:
        item_id = m.group(1)
        if item_id == "13":
            return route.fulfill(status=404, content_type="text/html", body=NOT_FOUND)
        return route.fulfill(status=200, content_type="text/html; charset=utf-8", body=product_html(item_id))
    if url.path == "/":
        return route.fulfill(status=200, content_type="text/html", body="<html><title>Lazada</title>home</html>")
    return route.fulfill(status=404, content_type="text/html", body=NOT_FOUND)


def test_lazada_crawl_against_fake_site(tmp_path, monkeypatch):
    STATE.update(solved=False, requests=[])
    pauses = []

    def person_solves(msg):
        pauses.append(msg)
        STATE["solved"] = True
    monkeypatch.setattr(F, "human_pause", person_solves)
    monkeypatch.setattr(C, "_pause", lambda *a, **k: None)
    cfg = make_cfg("lazada", profile=PROFILE_OIL, lazada={"target": 4, "buffer_ratio": 0.5, "max_pages": 5},
                   timeouts={"page_load_ms": 20000})
    store = RunStore("lazada", "t1", root=tmp_path)

    with B.open_context(tmp_path / "profile", headless=True) as ctx:
        ctx.route("https://www.lazada.vn/**", handle)
        C.crawl(ctx, store, cfg)

    pages = sorted(p.name for p in (store.dir / "search").glob("page_*.json"))
    assert pages == ["page_00.json", "page_01.json", "page_02.json"]      # third page empty -> end marker
    assert store.search_end_path.exists()
    assert len(pauses) == 1                                             # captcha on page 2 -> pause -> retry
    cands = read_json(store.candidates_path)
    assert [c["item_id"] for c in cands["kept"]] == ["11", "13", "15", "16"]
    assert [c["search_rank"] for c in cands["kept"]] == [1, 3, 4, 5]     # 12 (filter) counted, 14 (ad) not
    reasons = {c["item_id"]: c["reason"] for c in cands["excluded"]}
    assert reasons["14"] == "quảng cáo" and "Lọc" in reasons["12"]
    saved = sorted(p.stem for p in (store.dir / "items").glob("*.json"))
    assert saved == ["77_11", "77_15", "77_16"]
    assert "404" in store.load_failures()["77_13"]
    raw = read_json(store.dir / "items" / "77_15.json")
    assert raw["module_data"]["data"]["root"]["fields"]["product"]["title"].startswith("Nhớt mẫu 15")
    assert raw["tracking_data"]["pdt_name"] == "a } b"                 # brace scanner respects strings

    # export end to end
    from ecommerce.platforms.lazada.parse.dataset import build_dataset
    dataset = build_dataset(store, cfg)
    assert [p.item_id for p in dataset.products] == ["11", "15", "16"]
    assert dataset.products[0].sales.total == 121 and dataset.products[0].specs.attributes["grade"] == "10W-40"

    # re-run: nothing saved is fetched again
    STATE["requests"].clear()
    with B.open_context(tmp_path / "profile", headless=True) as ctx:
        ctx.route("https://www.lazada.vn/**", handle)
        C.crawl(ctx, store, cfg)
    fetched = [r for r in STATE["requests"] if r.startswith("/products/")]
    assert fetched == ["/products/x-i13-s130.html"]                    # only the earlier 404 is retried
