"""Drive the real crawler code against a fake, local 'Shopee'.

The fake site behaves like the real one where it matters for our plumbing:
pages are shells whose JS fetches the JSON APIs after load, the ratings block
only loads when scrolled into view, the review pager must be clicked, and one
product redirects to a captcha page.

Runs only when a Chromium binary is available:
    ECOMMERCE_CHROME_EXECUTABLE=/path/to/chrome pytest tests/integration
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from ecommerce.ingestion import browser as B
from ecommerce.ingestion.raw_store import RunStore, read_json
from ecommerce.platforms.shopee.extract import detail as D
from ecommerce.platforms.shopee.extract import listing as L
from helpers import make_cfg

CHROME = os.environ.get("ECOMMERCE_CHROME_EXECUTABLE")
pytestmark = pytest.mark.skipif(not CHROME, reason="set ECOMMERCE_CHROME_EXECUTABLE to run")

P = 100000
STATE = {"captcha_solved": False, "logged_in": False, "api_calls": []}

TITLES = ["Bình giữ nhiệt {n} 500ml", "Ly giữ nhiệt {n} 900ml", "Hộp cơm giữ nhiệt {n}",
          "Cốc giữ nhiệt {n} có ống hút", "Túi giữ nhiệt {n}"]


def search_json(newest: int) -> dict:
    items = []
    for i in range(newest, newest + 60):
        items.append({"item_basic": {"itemid": 1000 + i, "shopid": 1, "name": TITLES[i % 5].format(n=i),
                                     "price": 100000 * P, "sold": 10, "historical_sold": 100,
                                     "images": ["a", "b"], "image": "a"},
                      "adsid": 5 if i % 20 == 7 else None})
    return {"error": None, "items": items, "nomore": newest >= 120}


def pdp_json(itemid: int) -> dict:
    # like real Shopee: a product without variations still has one model
    return {"error": None, "data": {"item": {"item_id": itemid, "shop_id": 1, "title": f"Bình {itemid}",
                                             "models": [{"model_id": 1, "price": 100000 * P, "has_stock": True}],
                                             "tier_variations": []}}}


def ratings_json(offset: int) -> dict:
    return {"error": 0, "data": {"ratings": [
        {"cmtid": offset + k, "author_username": f"u{offset + k}", "rating_star": 5,
         "comment": "tốt", "ctime": 1_700_000_000 - (offset + k)} for k in range(6)]}}


SEARCH_HTML = """<html><body><div id=list>loading</div><script>
const LOGGED_IN = %s;
const q = new URLSearchParams(location.search);
const newest = Number(q.get('page') || 0) * 60;
setTimeout(() => fetch('/api/v4/search/search_items?by=' + q.get('sortBy') + '&keyword=' +
  encodeURIComponent(q.get('keyword')) + '&limit=60&newest=' + newest)
  .then(r => r.json()).then(d => {
    // real Shopee: answers the API, THEN bounces a guest to the login wall
    if (!LOGGED_IN) location.href = '/verify/traffic/error?home_url=x&is_logged_in=false&next=y';
    document.getElementById('list').textContent = d.items.length; }), 300);
// a widget firing a SECOND search_items later -- the crawler must keep the first
setTimeout(() => fetch('/api/v4/search/search_items?by=relevancy&keyword=widget&newest=999'), 900);
</script></body></html>"""

PRODUCT_HTML = """<html><body style="margin:0">
<div style="height:4000px">product {itemid}</div>
<div class="product-ratings" id=ratings style="height:600px">ratings
  <div class="shopee-page-controller product-ratings__page-controller">
    <button>1</button><button onclick="loadRatings(6)">2</button></div></div>
<script>
fetch('/api/v4/recommend/get_pc?item_id=999');   // unrelated widget
setTimeout(() => fetch('/api/v4/pdp/get_pc?item_id={itemid}&shop_id=1&tz_offset_minutes=420'), 400);
function loadRatings(off) {{ fetch('/api/v2/item/get_ratings?itemid={itemid}&offset=' + off + '&limit=6'); }}
new IntersectionObserver(es => es.forEach(e => {{ if (e.isIntersecting) loadRatings(0); }}),
  {{}}).observe(document.getElementById('ratings'));
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, body: str, ctype: str, status: int = 200, headers: dict | None = None):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path.startswith("/api/"):
            STATE["api_calls"].append(self.path)
        if url.path == "/search":
            return self._send(SEARCH_HTML % ("true" if STATE["logged_in"] else "false"), "text/html")
        if url.path == "/api/v4/search/search_items":
            return self._send(json.dumps(search_json(int(q.get("newest", 0)))), "application/json")
        if url.path.startswith("/product/"):
            itemid = int(url.path.rstrip("/").split("/")[-1])
            if itemid == 1003 and not STATE["captcha_solved"]:
                return self._send("", "text/html", 302, {"Location": "/verify/captcha?anti_bot=1"})
            return self._send(PRODUCT_HTML.format(itemid=itemid), "text/html")
        if url.path in ("/verify/captcha", "/verify/traffic/error"):
            return self._send("<html>captcha</html>", "text/html")
        if url.path == "/api/v4/pdp/get_pc":
            itemid = int(q["item_id"])
            if itemid == 1005:
                return self._send(json.dumps({"error": 4, "data": None}), "application/json")  # 90309999 = cooldown path, unit-tested
            return self._send(json.dumps(pdp_json(itemid)), "application/json")
        if url.path == "/api/v4/recommend/get_pc":
            return self._send("{}", "application/json")
        if url.path == "/api/v2/item/get_ratings":
            return self._send(json.dumps(ratings_json(int(q["offset"]))), "application/json")
        self._send("not found", "text/plain", 404)


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_listing_and_details_against_fake_site(site, tmp_path, monkeypatch):
    monkeypatch.setattr(L, "SEARCH_URL", site + "/search?keyword={kw}&page={page}&sortBy={sort}")
    monkeypatch.setattr(D, "PRODUCT_URL", site + "/product/{shopid}/{itemid}")
    monkeypatch.setenv("ECOMMERCE_HOME", str(tmp_path))
    monkeypatch.setattr(L, "jitter_sleep", lambda *a, **k: None)
    monkeypatch.setattr(D, "jitter_sleep", lambda *a, **k: None)
    pauses = []
    holder = {}

    def fake_pause(msg):          # the "human" solves the captcha...
        # ...which is only possible if the captcha tab is still open
        assert any("/verify/captcha" in pg.url for pg in holder["ctx"].pages)
        pauses.append(msg)
        STATE["captcha_solved"] = True
    monkeypatch.setattr(D, "human_pause", fake_pause)
    login_pauses = []

    def fake_login(msg):          # the "human" logs in on the wall tab
        assert any("is_logged_in=false" in pg.url for pg in holder["ctx"].pages)
        login_pauses.append(msg)
        STATE["logged_in"] = True
    monkeypatch.setattr(L, "human_pause", fake_login)

    cfg = make_cfg(shopee={"target": 60, "buffer_ratio": 0, "max_pages": 5, "include_ads": False},
                   pacing={"max_attempts": 1, "long_break_every": 0},
                   timeouts={"click_pause_min_ms": 600, "click_pause_max_ms": 1000})
    store = RunStore("shopee", "t", root=tmp_path / "raw")

    with B.open_context(tmp_path / "profile", headless=True) as ctx:
        holder["ctx"] = ctx
        kept = L.crawl_listing(ctx, store, cfg)
        # 3 of every 5 titles are drinkware, ads removed -> needs 2 search pages
        assert len(kept) == 60
        assert len(list(store.iter_search_pages())) == 2
        first = read_json(store.search_path(0))
        assert "by=sales" in first["request_url"] and "newest=0" in first["request_url"]
        assert "newest=60" in read_json(store.search_path(1))["request_url"]
        assert len(login_pauses) == 1 and "NOT LOGGED IN" in login_pauses[0]

        started = time.monotonic()
        D.crawl_details(ctx, store, cfg, kept[:5])
        elapsed = time.monotonic() - started

    done = {p.stem for p in (store.dir / "items").glob("*.json")}
    # 1000 bottle, 1001 tumbler, 1003 cup (captcha, then solved), 1005 bottle (blocked payload)
    assert "1_1000" in done and "1_1003" in done
    assert "1_1005" not in done
    assert "1_1005" in store.load_failures()
    assert len(pauses) == 1 and "captcha" in pauses[0]

    raw = read_json(store.item_path(1, 1000))
    assert raw["pdp"]["data"]["item"]["item_id"] == 1000      # not the recommend widget
    offsets = sorted(json.loads(json.dumps(r))["data"]["ratings"][0]["cmtid"] for r in raw["ratings"])
    assert offsets == [0]              # only scrolls to load the star summary, never clicks page 2
    assert elapsed < 120

    # resume: a second run skips everything already on disk
    before = len(STATE["api_calls"])
    with B.open_context(tmp_path / "profile", headless=True) as ctx:
        L.crawl_listing(ctx, store, cfg)
        D.crawl_details(ctx, store, cfg, [c for c in kept[:5] if c.itemid != 1005])
    assert len(STATE["api_calls"]) == before
