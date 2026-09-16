"""Drive the real TikTok crawler in real Chrome against a fake shop.tiktok.com.

Playwright routes intercept every request to https://shop.tiktok.com, so the
page's own XMLHttpRequest (same origin, same cookies) is exercised exactly as
on the real site. The fake site:
    * serves keyword pages with __MODERN_ROUTER_DATA__ and related links,
    * answers one keyword page with a 'Security Check' page until the
      "person" solves it (the crawler must pause, then retry the same page),
    * 404s one product (recorded as a failure, the run goes on),
    * and a re-run must not request anything already saved.

    ECOMMERCE_CHROME_EXECUTABLE=/path/to/chrome pytest tests/integration
"""
from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path

import pytest

from ecommerce.domain.profile import Discovery, TikTokDiscovery
from ecommerce.ingestion import browser as B
from ecommerce.ingestion.raw_store import RunStore, read_json
from ecommerce.platforms.tiktok.extract import crawl as C
from ecommerce.platforms.tiktok.extract import fetch as F
from helpers import PROFILE, make_cfg

CHROME = os.environ.get("ECOMMERCE_CHROME_EXECUTABLE")
pytestmark = pytest.mark.skipif(not CHROME, reason="set ECOMMERCE_CHROME_EXECUTABLE to run")

FIX = Path(__file__).parents[1] / "fixtures"
STATE = {"solved": False, "requests": []}


def router_page(components) -> str:
    data = json.dumps({"loaderData": {"layout": {}, "(region)/x/page": {"page_config": {"components_map": components}}}},
                      ensure_ascii=False)
    return (f"<!doctype html><html><head><title>TikTok Shop</title></head><body>"
            f"<script type='application/json' id='__MODERN_ROUTER_DATA__'>{html.escape(data, quote=False)}</script>"
            f"</body></html>")


def keyword_components(related: list[str], ids: list[str]):
    base = json.loads((FIX / "tiktok_keyword_components.json").read_text(encoding="utf-8"))
    feed = base[1]["component_data"]["products"]
    products = []
    for n, pid in enumerate(ids):
        p = json.loads(json.dumps(feed[0]))
        p["product_id"], p["title"] = pid, f"Bình giữ nhiệt mẫu {pid} 500ml"
        p["sold_info"]["sold_count"] = 1000 * (n + 1)
        p["seller_info"]["seller_id"] = "9"
        products.append(p)
    products.append(json.loads(json.dumps(feed[1])))          # thermal shirt ("áo giữ nhiệt"): filtered out
    base[1]["component_data"]["products"] = products
    base[2]["component_data"]["related_links"] = [{"link": f"https://shop.tiktok.com/vn/k/{s}"} for s in related]
    return base


def pdp_components(pid: str):
    raw = json.loads((FIX / "tiktok_pdp_raw.json").read_text(encoding="utf-8"))
    info = raw["product_info"]
    info["product_info"]["product_model"]["product_id"] = pid
    info["product_info"]["product_model"]["sold_count"] = str(int(pid) * 7)
    return [{"component_type": "product_info", "component_name": "product_info", "component_data": info}]


SECURITY = "<!doctype html><html><head><title>Security Check</title></head><body>drag the slider</body></html>"
NOT_FOUND = "<!doctype html><html><head><title>404 Not Found</title></head><body>404</body></html>"


def handle(route):
    path = re.sub(r"^https://shop\.tiktok\.com", "", route.request.url)
    STATE["requests"].append(path)
    if path in ("/vn", "/vn/k/giu-nhiet"):
        body = router_page(keyword_components(["binh-giu-nhiet-mini", "ao-giu-nhiet"], ["11", "12", "13"]))
    elif path == "/vn/k/binh-giu-nhiet-mini":
        if not STATE["solved"]:
            return route.fulfill(status=200, content_type="text/html", body=SECURITY)
        body = router_page(keyword_components(["giu-nhiet"], ["13", "14", "15"]))
    elif path.startswith("/vn/pdp/"):
        pid = path.rsplit("/", 1)[1]
        if pid == "12":
            return route.fulfill(status=404, content_type="text/html", body=NOT_FOUND)
        body = router_page(pdp_components(pid))
    else:
        return route.fulfill(status=404, content_type="text/html", body=NOT_FOUND)
    route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)


def test_tiktok_crawl_against_fake_site(tmp_path, monkeypatch):
    STATE.update(solved=False, requests=[])
    pauses = []

    def person_solves(msg):
        pauses.append(msg)
        STATE["solved"] = True
    monkeypatch.setattr(F, "human_pause", person_solves)
    monkeypatch.setattr(C, "_pause", lambda *a, **k: None)
    profile = PROFILE.model_copy(update={"discovery": Discovery(tiktok=TikTokDiscovery(
        seed_slugs=["giu-nhiet"], slug_include="giu-nhiet", slug_exclude="(^|-)ao(-|$)"))})
    cfg = make_cfg("tiktok", profile=profile, tiktok={"target": 3, "buffer_ratio": 1.0, "max_keyword_pages": 10},
                   timeouts={"page_load_ms": 20000})
    store = RunStore("tiktok", "t1", root=tmp_path)

    with B.open_context(tmp_path / "profile", headless=True) as ctx:
        ctx.route("https://shop.tiktok.com/**", handle)
        C.crawl(ctx, store, cfg)

    pages = [read_json(p)["slug"] for p in sorted((store.dir / "search").glob("page_*.json"))]
    assert pages == ["giu-nhiet", "binh-giu-nhiet-mini"]          # ao-giu-nhiet page never visited
    assert len(pauses) == 1                                        # captcha -> pause -> same page retried
    cands = read_json(store.candidates_path)
    # by listing sold (max over pages), ties by first page seen
    assert [c["product_id"] for c in cands["kept"]] == ["13", "15", "12", "14", "11"]
    saved = sorted(p.stem for p in (store.dir / "items").glob("*.json"))
    assert saved == ["9_11", "9_13", "9_14", "9_15"]
    assert "404" in store.load_failures()["9_12"]
    raw = read_json(store.dir / "items" / "9_14.json")
    assert raw["product_info"]["product_info"]["product_model"]["product_id"] == "14"

    # re-run: nothing saved is fetched again (only the start page + the 404 retry)
    STATE["requests"].clear()
    with B.open_context(tmp_path / "profile", headless=True) as ctx:
        ctx.route("https://shop.tiktok.com/**", handle)
        C.crawl(ctx, store, cfg)
    assert [r for r in STATE["requests"] if r.startswith("/vn/pdp/")] == ["/vn/pdp/12"]
    assert not [r for r in STATE["requests"] if r == "/vn/k/binh-giu-nhiet-mini"]
