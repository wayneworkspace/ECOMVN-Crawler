"""One test per bug found in code review, so they stay fixed."""
import copy

import pytest

from ecommerce.domain.candidate import ShopeeCandidate
from ecommerce.domain.product import Product, Shop
from ecommerce.ingestion.raw_store import RunStore
from ecommerce.platforms.shopee.extract import detail as D
from ecommerce.platforms.shopee.parse import common as C
from ecommerce.platforms.shopee.parse.dataset import restrict_to_candidates
from ecommerce.platforms.shopee.parse.product import parse_product
from ecommerce.transformation import specs as A
from helpers import PROFILE, make_cfg


def parse(raw, **kw) -> dict:
    return parse_product(raw, PROFILE, **kw).to_row()


def product(shop_id, item_id, title="Bình giữ nhiệt", search_rank=None) -> Product:
    return Product(platform="shopee", item_id=item_id, url="u", title=title,
                   shop=Shop(id=shop_id), search_rank=search_rank)


# ---- parser must survive odd-but-plausible payload shapes -----------------------
MUTATIONS = {
    "ctime in milliseconds": lambda r: r["pdp"]["data"]["item"].update(ctime=1754464878000),
    "tier_index bare int": lambda r: r["pdp"]["data"]["item"]["models"][0].update(tier_index=1, extinfo={}),
    "tier option None / int": lambda r: r["pdp"]["data"]["item"]["tier_variations"][0].update(options=[None, 500]),
    "model name int": lambda r: r["pdp"]["data"]["item"]["models"][0].update(name=123),
    "category name int": lambda r: r["pdp"]["data"]["item"]["categories"].append({"display_name": 7}),
    "price_info not dict": lambda r: r["pdp"]["data"]["item"]["models"][0].update(price_info=[1]),
    "product_price is list": lambda r: r["pdp"]["data"].update(product_price=[]),
    "product_review is list": lambda r: r["pdp"]["data"].update(product_review=[]),
    "ratings data is list": lambda r: r["ratings"].append({"data": []}),
    "summary is list": lambda r: r["ratings"][0]["data"].update(item_rating_summary=[]),
    "comment int": lambda r: r["ratings"][0]["data"]["ratings"][0].update(comment=5),
    "images int": lambda r: r["ratings"][0]["data"]["ratings"][0].update(images=3),
    "cmtid list": lambda r: r["ratings"][0]["data"]["ratings"][0].update(cmtid=[1, 2]),
    "star N/A": lambda r: r["pdp"]["data"]["product_review"].update(rating_star="N/A"),
    "huge number": lambda r: r["pdp"]["data"]["item"].update(liked_count=float("inf")),
    "images as string": lambda r: r["pdp"]["data"].update(product_images={"images": "abc"}),
    "attribute values dict": lambda r: r["pdp"]["data"]["item"]["attributes"].append({"name": "X", "value": {"name": "Y"}}),
}


@pytest.mark.parametrize("name", MUTATIONS)
def test_parser_survives(load, name):
    raw = load("shopee_item_raw.json")
    MUTATIONS[name](raw)
    record = parse(copy.deepcopy(raw))
    assert record["item_id"] == 111


def test_millisecond_timestamps_become_dates():
    assert C.ts_to_date(1754464878000) == C.ts_to_date(1754464878)


def test_images_string_is_one_image_not_characters(load):
    raw = load("shopee_item_raw.json")
    raw["pdp"]["data"]["product_images"] = {"images": "abc"}
    raw["pdp"]["data"]["item"]["image"] = None
    raw["candidate"]["basic"]["image"] = None
    assert parse(raw)["images"] == [C.IMAGE_BASE + "abc"]


@pytest.mark.parametrize("raw, expected", [("22.5%", 22), ("-25%", 25), (True, None), (150, None), (0, None)])
def test_discount_pct(raw, expected):
    assert C.discount_pct(raw) == expected


# ---- regex false positives ------------------------------------------------
@pytest.mark.parametrize("text", [
    "Hàng có sẵn tại cửa hàng", "Shop cập nhật mẫu mới", "thiết kế thẩm mỹ", "đức tính kiên nhẫn",
])
def test_origin_ignores_common_words(text):
    assert A.extract_origin({}, "", text).value is None


def test_origin_still_found_with_context():
    assert A.extract_origin({}, "", "Xuất xứ: Hàn Quốc").value == "Hàn Quốc"
    assert A.extract_origin({}, "", "Hàng nhập khẩu Nhật Bản").value == "Nhật Bản"


@pytest.mark.parametrize("text, is_color", [
    ("Cam kết chính hãng", False), ("Ghi chú", False), ("can be used", False),
    ("Cam 500ml", True), ("Be", True), ("Ghi xám", True),
])
def test_color_words(text, is_color):
    assert A.looks_like_color(text) is is_color


def test_satisfaction_phrase_is_not_an_inner_lining():
    assert A.extract_materials({}, "", "không hài lòng về chất lượng inox")["inner"].value is None


# ---- storage / export ------------------------------------------------------
def test_latest_run_sorts_numeric_suffix(tmp_path):
    for name in ("20260910", "20260910_2", "20260910_9", "20260910_10"):
        (tmp_path / "shopee" / name).mkdir(parents=True)
    assert RunStore.latest("shopee", root=tmp_path).run_id == "20260910_10"


def test_export_uses_current_filter_and_rank():
    products = [product(1, 1, search_rank=9), product(2, 2, search_rank=1)]
    kept = [ShopeeCandidate(shopid=1, itemid=1, search_rank=4, product_type="Bình")]
    out = restrict_to_candidates(products, kept)
    assert [(p.item_id, p.search_rank) for p in out] == [(1, 4)]


def test_export_rechecks_the_title_with_the_current_filter():
    # candidates.json was built by an older filter that let a food jar through
    products = [product(1, 1, "Bình ủ cháo giữ nhiệt inox 304"), product(1, 2, "[Tặng túi] Bình giữ nhiệt 500ml")]
    kept = [ShopeeCandidate(shopid=1, itemid=1, search_rank=1), ShopeeCandidate(shopid=1, itemid=2, search_rank=2)]
    assert [p.item_id for p in restrict_to_candidates(products, kept, PROFILE)] == [2]


# ---- crawl flow ------------------------------------------------------------
class _FakePage:
    def wait_for_timeout(self, ms):
        pass

    def is_closed(self):
        return False


class _FakeContext:
    pages = [_FakePage()]


def test_soft_block_streak_pauses_for_human(tmp_path, monkeypatch):
    pauses = []
    monkeypatch.setattr(D, "human_pause", lambda msg: pauses.append(msg))
    monkeypatch.setattr(D, "jitter_sleep", lambda *a, **k: None)

    def always_soft_blocked(*a, **k):
        raise D.SoftBlocked("get_pc trả lỗi error=90309999")
    monkeypatch.setattr(D, "fetch_product", always_soft_blocked)

    store = RunStore("shopee", "t", root=tmp_path)
    cands = [{"shopid": 1, "itemid": i, "name": f"Bình {i}", "search_rank": i} for i in range(7)]
    cfg = make_cfg(pacing={"max_attempts": 1, "long_break_every": 0})
    D.crawl_details(_FakeContext(), store, cfg, cands)
    assert len(pauses) == 2                      # after products 3 and 6
    assert "silent block" in pauses[0]
    assert len(store.load_failures()) == 7


# ---- walls seen on the real site -------------------------------------------
def test_login_required_page_is_a_login_wall_not_traffic():
    from ecommerce.ingestion.browser import block_kind, wall_help
    url = ("https://shopee.vn/verify/traffic/error?home_url=https%3A%2F%2Fshopee.vn"
           "&is_logged_in=false&next=https%3A%2F%2Fshopee.vn%2Fsearch%3Fkeyword%3D")
    assert block_kind(url) == "login_wall"
    assert "ecommerce login" in wall_help("login_wall")
    assert block_kind("https://shopee.vn/verify/captcha?anti_bot_tracking_id=1") == "captcha"
    assert block_kind("https://shopee.vn/search?keyword=x") is None


class _Ctx:
    def __init__(self, cookies):
        self._c = cookies

    def cookies(self, url):
        return [{"name": k, "value": v} for k, v in self._c.items()]


@pytest.mark.parametrize("cookies, state", [
    ({}, False),
    ({"SPC_U": "-", "SPC_F": "x"}, False),
    ({"SPC_U": "123456", "SPC_F": "x"}, True),
    ({"SPC_ST": "tok", "SPC_F": "x"}, True),
    ({"SPC_F": "x"}, None),
])
def test_login_state_from_cookies(cookies, state):
    from ecommerce.platforms.shopee.extract.session import shopee_login_state
    assert shopee_login_state(_Ctx(cookies)) is state


def test_crawl_refuses_to_run_as_guest():
    from ecommerce.platforms import get_adapter
    adapter = get_adapter("shopee")
    with pytest.raises(SystemExit) as exc:
        adapter.check_session(_Ctx({"SPC_U": "-", "SPC_F": "x"}))
    assert "ecommerce login" in str(exc.value)
    adapter.check_session(_Ctx({"SPC_U": "42"}))      # logged in: no exit


@pytest.mark.parametrize("rec, text", [
    ({"material_inner": "Gốm sứ", "material_all": "Gốm sứ, Inox 316"}, "Trong: Gốm sứ · Khác: Inox 316"),
    ({"material_outer": "Inox 304", "material_all": "Inox 304"}, "Ngoài: Inox 304"),
    ({"material_all": "Inox 316, Nhựa PP"}, "Inox 316, Nhựa PP (không rõ trong/ngoài)"),
    ({}, None),
])
def test_material_text(rec, text):
    from ecommerce.consumption.excel.columns import material_text
    assert material_text(rec) == text


# ---- per-SKU stock -----------------------------------------------------------
def test_sku_stock_merged_into_variants_and_total(load):
    raw = load("shopee_item_raw.json")
    raw["sku_stock"] = {"complete": True, "clicks": 3, "by_model": {
        "1": {"available": 40, "status": "Còn hàng"}, "2": {"available": 0, "status": "Hết hàng"},
        "3": {"available": 12, "status": "Còn hàng"}}}
    r = parse(raw)
    assert [v["stock"] for v in r["variants"]] == [40, 0, 12]
    assert r["stock_total"] == 52
    assert r["stock_value"] == 52
    assert r["stock_state"] == "Còn hàng (2/3 SKU còn hàng)"


def test_partial_sku_stock_is_a_lower_bound(load):
    raw = load("shopee_item_raw.json")
    raw["sku_stock"] = {"complete": False, "by_model": {"1": {"available": 40, "status": "Còn hàng"}}}
    r = parse(raw)
    assert r["stock_total"] is None and r["stock_value"] == 40
    assert "tồn kho tối thiểu: đếm được 1/3 SKU" in r["stock_state"]


def test_needs_crawl_recrawls_items_without_sku_stock(tmp_path):
    from ecommerce.ingestion.raw_store import write_json
    store = RunStore("shopee", "t", root=tmp_path)
    cand = {"shopid": 1, "itemid": 2}
    assert D.needs_crawl(store, cand, sku_stock=True)                 # not crawled
    write_json(store.item_path(1, 2), {"pdp": {}})
    assert not D.needs_crawl(store, cand, sku_stock=False)
    assert D.needs_crawl(store, cand, sku_stock=True)                 # old file, no stock
    write_json(store.item_path(1, 2), {"pdp": {}, "sku_stock": {"complete": False}})
    assert not D.needs_crawl(store, cand, sku_stock=True)             # capped: don't loop


def test_pause_survives_closed_tab(tmp_path, monkeypatch, load):
    """Real run: the tab used for waiting between products was gone -> crash."""
    slept = []
    monkeypatch.setattr(D.time, "sleep", lambda s: slept.append(s))

    class ClosedPage:
        def is_closed(self):
            return False

        def wait_for_timeout(self, ms):
            raise RuntimeError("Page.wait_for_timeout: Target page, context or browser has been closed")

    class Ctx:
        pages = [ClosedPage()]

    ok = {"n": 0}

    def fake_fetch(*a, **k):
        ok["n"] += 1
        return load("shopee_item_raw.json")      # a real-looking product: the schema guard stays quiet
    monkeypatch.setattr(D, "fetch_product", fake_fetch)
    store = RunStore("shopee", "t", root=tmp_path)
    cands = [{"shopid": 1, "itemid": i, "name": "x", "search_rank": i} for i in range(3)]
    D.crawl_details(Ctx(), store, make_cfg(pacing={"long_break_every": 0}), cands)
    assert ok["n"] == 3 and len(slept) == 2


# ---- /verify/traffic (real run 10/09: blocked after ~25 products) -------------
def test_traffic_wall_cools_down_and_retries_same_product(tmp_path, monkeypatch):
    slept = []
    monkeypatch.setattr(D.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(D, "jitter_sleep", lambda *a, **k: None)
    calls = []

    def fetch(ctx, cand, *a, **k):
        calls.append(cand.itemid)
        if len(calls) <= 2:
            raise D.TrafficBlocked("https://shopee.vn/verify/traffic?anti_bot_tracking_id=x")
        return {"ratings": [], "shop": [], "sku_stock": None}
    monkeypatch.setattr(D, "fetch_product", fetch)
    store = RunStore("shopee", "t", root=tmp_path)
    cands = [{"shopid": 1, "itemid": i, "name": "x", "search_rank": i} for i in range(2)]
    cfg = make_cfg(pacing={"long_break_every": 0, "block_cooldown_min": 30, "max_block_cooldowns": 3})
    D.crawl_details(_FakeContext(), store, cfg, cands)
    assert calls == [0, 0, 0, 1]                      # same product retried, not skipped
    assert store.load_failures() == {}
    assert sum(slept) >= (30 + 60) * 60               # 30 then 60 minutes


def test_traffic_wall_gives_up_after_max_cooldowns(tmp_path, monkeypatch):
    monkeypatch.setattr(D.time, "sleep", lambda s: None)
    monkeypatch.setattr(D, "jitter_sleep", lambda *a, **k: None)
    calls = []

    def fetch(ctx, cand, *a, **k):
        calls.append(cand.itemid)
        raise D.TrafficBlocked("wall")
    monkeypatch.setattr(D, "fetch_product", fetch)
    store = RunStore("shopee", "t", root=tmp_path)
    cands = [{"shopid": 1, "itemid": i, "name": "x", "search_rank": i} for i in range(5)]
    D.crawl_details(_FakeContext(), store, make_cfg(pacing={"max_block_cooldowns": 2, "long_break_every": 0}), cands)
    assert calls == [0, 0, 0]                         # stops instead of burning the list
    assert store.load_failures() == {}                # nothing wrongly marked failed


def test_two_pass_crawl_reopens_only_products_without_sku_stock(tmp_path):
    from ecommerce.cli import _apply_pass
    from ecommerce.ingestion.raw_store import write_json
    from ecommerce.platforms.shopee.extract.detail import needs_crawl
    cfg = make_cfg(shopee={"sku_stock": True})
    assert _apply_pass(cfg, 1).shopee.sku_stock is False
    assert _apply_pass(cfg, 2).shopee.sku_stock is True
    assert _apply_pass(cfg, None) is cfg and cfg.shopee.sku_stock is True   # config untouched
    store = RunStore("shopee", "r", root=tmp_path)
    a, b, c = ({"shopid": 1, "itemid": i} for i in (1, 2, 3))
    write_json(store.item_path(1, 1), {"sku_stock": None})             # saved by pass 1
    write_json(store.item_path(1, 2), {"sku_stock": {"by_model": {}}})  # full
    # pass 1: only the product never opened
    assert [needs_crawl(store, x, False) for x in (a, b, c)] == [False, False, True]
    # pass 2: pass-1 products are reopened for their SKU stock
    assert [needs_crawl(store, x, True) for x in (a, b, c)] == [True, False, True]


def test_risk_control_error_cools_down_instead_of_retrying(tmp_path, monkeypatch):
    """get_pc {"error": 90309999}: stop sending requests (cooldown), don't burn the product."""
    calls, slept = [], []

    def blocked(*a, **k):
        calls.append(1)
        raise D.TrafficBlocked("get_pc error=90309999")
    monkeypatch.setattr(D, "fetch_product", blocked)
    monkeypatch.setattr(D, "jitter_sleep", lambda *a, **k: None)
    monkeypatch.setattr(D.time, "sleep", lambda s: slept.append(s))
    store = RunStore("shopee", "r", root=tmp_path)
    cfg = make_cfg(pacing={"block_cooldown_min": 1, "max_block_cooldowns": 2})
    D.crawl_details(_FakeContext(), store, cfg, [{"shopid": 1, "itemid": 1, "name": "x"}])
    assert len(calls) == 3                       # first try + one retry after each of 2 cooldowns
    assert sum(slept) == 60 + 120                # 1 min, then 2 min
    assert store.load_failures() == {}           # the product is not blamed


# ---- every crawl is a fresh snapshot (13/09) -----------------------------------
def _args(**kw):
    import argparse
    return argparse.Namespace(**{"platform": "shopee", "run": None, "new_run": False, "keyword": "giữ nhiệt",
                                 "domain": None, "max_products": None, **kw})


def test_crawl_opens_a_new_run_and_resume_continues(tmp_path, monkeypatch, caplog):
    """`crawl` must open a NEW run; only `resume` continues the previous one.

    Prices and stock change daily: mixing two days into one Excel file is wrong.
    """
    from ecommerce import cli
    from ecommerce.ingestion.raw_store import RunStore, write_json
    monkeypatch.setenv("ECOMMERCE_HOME", str(tmp_path))          # data/raw under tmp_path
    cfg = cli._config(_args())
    root = cfg.paths.raw

    old = RunStore.new("shopee", root, keyword="giữ nhiệt")
    write_json(old.candidates_path, {"kept": [{"shopid": 1, "itemid": i} for i in range(5)]})
    write_json(old.item_path(1, 0), {"pdp": {}})                 # 1/5 products crawled so far

    new = cli._store(_args(new_run=True), cfg, create=True)      # `crawl`
    assert new.run_id != old.run_id and not list((new.dir / "items").glob("*.json"))
    assert "resume" in caplog.text and "1/5" in caplog.text      # the unfinished run is mentioned
    assert new.load_meta()["keyword"] == "giữ nhiệt"             # run.json written

    again = cli._store(_args(new_run=False), cfg, create=True)   # `resume`
    assert again.run_id == new.run_id                            # the latest, created above
    named = cli._store(_args(run=old.run_id), cfg, create=True)  # --run <name>
    assert named.run_id == old.run_id
    assert cli._progress(old) == (1, 5) and cli._progress(new) == (0, 0)
    # a run for another keyword is not "the latest" for this one
    other = RunStore.new("shopee", root, keyword="ly sứ")
    assert RunStore.latest("shopee", root, keyword="giữ nhiệt").run_id == new.run_id
    assert RunStore.latest("shopee", root).run_id == other.run_id


def test_main_sheet_price_range_covers_every_sku(load):
    """If the main sheet says 'lowest/highest price', it must really be the lowest/highest.

    Shopee often reports price_min = price_max = the price of ONE variant that is
    on promotion: measured on 40 real products, 13 had item.price_max below the
    highest SKU price (420,000 while an SKU sold for 880,000). Opening the Detail
    sheet next to the main one shows the contradiction at once (decisions.md #19).
    """
    from ecommerce.platforms.shopee.parse.product import parse_product
    raw = load("shopee_item_raw.json")
    item = raw["pdp"]["data"]["item"]
    # the site collapses the price range to a single level while the SKUs spread wide
    item["price_min"] = item["price_max"] = item["price"] = 30_000_000_000       # 300,000 VND
    for model, price in zip(item["models"], (25_000_000_000, 30_000_000_000, 88_000_000_000), strict=False):
        model["price"] = price                                                   # 250k / 300k / 880k

    row = parse_product(raw, PROFILE).to_row()
    sku_prices = [v["price"] for v in row["variants"] if v["price"]]
    assert row["price_min"] <= min(sku_prices), f"{row['price_min']} > cheapest SKU {min(sku_prices)}"
    assert row["price_max"] >= max(sku_prices), f"{row['price_max']} < priciest SKU {max(sku_prices)}"
    assert (row["price_min"], row["price_max"]) == (250_000, 880_000)
