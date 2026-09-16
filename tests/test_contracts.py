"""contracts/: the rule tables must agree with the readers in transform/.

The two sync tests are the point of this file:
  * delete every source of a rule  -> the Excel field it feeds must go empty
    (else the reader uses a place the rule does not list: false alarms)
  * keep only ONE source of a rule -> the Excel field must still be filled
    (else the rule lists a place the reader does not use: missed alarms)
"""
import copy

import pytest

from ecommerce.contracts import SchemaGuard, check_file, rules_for
from ecommerce.contracts.check import check_section, load_baseline, make_baseline
from ecommerce.contracts.paths import delete_at, values_at
from ecommerce.contracts.rules import NUMBER, kind_of
from ecommerce.contracts.snapshot import compare, structure
from ecommerce.platforms.shopee.parse.product import parse_product as parse_shopee
from ecommerce.platforms.tiktok.parse.listing import parse_keyword_page
from ecommerce.platforms.tiktok.parse.product import parse_product as parse_tiktok


# ---- samples ------------------------------------------------------------------
@pytest.fixture
def shopee_raw(load):
    """The fixture product after pass 2 (per-SKU stock read), so every rule has data."""
    raw = load("shopee_item_raw.json")
    raw["sku_stock"] = {"complete": True, "by_model": {
        "1": {"available": 40, "status": "Còn hàng"}, "2": {"available": 0, "status": "Hết hàng"},
        "3": {"available": 12, "status": "Còn hàng"}}}
    return raw


@pytest.fixture
def tiktok_raw(load):
    return load("tiktok_pdp_raw.json")


SAMPLES = {"shopee": ("shopee_raw", lambda raw: parse_shopee(raw).to_row()),
           "tiktok": ("tiktok_raw", lambda raw: parse_tiktok(raw).to_row())}


def _empty(value) -> bool:
    return value in (None, "", [], {}, 0)


def _present(raw, rule, source) -> bool:
    values = values_at(raw, source)
    if rule.positive:
        values = [v for v in values if kind_of(v) != NUMBER or float(v) > 0]
    return bool(values)


def _target(path):
    """What 'the site stopped sending this' removes. For 'x.rating_count.0' that
    is the whole array (a site drops a field, it does not null out element 0)."""
    head, _, last = path.rpartition(".")
    return head if last.isdigit() else path


def _drop(raw, path):
    delete_at(raw, _target(path))


def _cases(kind_of_test):
    for platform in SAMPLES:
        for rule in rules_for(platform, "item"):
            if not rule.feeds:
                continue
            if kind_of_test == "all" and not rule.also:
                yield pytest.param(platform, rule, id=f"{platform}:{rule.name}")
            if kind_of_test == "each":
                for source in rule.sources:
                    yield pytest.param(platform, rule, source, id=f"{platform}:{rule.name}:{source}")


# Sources the reader uses only under a condition the fixture does not meet.
CONDITIONAL = {
    "pdp.data.product_price.price.range_min": "is the selling price only when there is NO post-voucher price",
    "pdp.data.product_price.price.single_value": "is the selling price only when there is NO post-voucher price",
}


@pytest.mark.parametrize("platform, rule", list(_cases("all")))
def test_deleting_every_source_empties_the_excel_field(request, platform, rule):
    fixture_name, to_row = SAMPLES[platform]
    raw = request.getfixturevalue(fixture_name)
    before = to_row(copy.deepcopy(raw))
    assert not all(_empty(before[f]) for f in rule.feeds), f"fixture has no data for rule {rule.name!r}"
    for source in rule.sources:
        _drop(raw, source)
    after = to_row(raw)
    filled = {f: after[f] for f in rule.feeds if not _empty(after[f])}
    assert not filled, (f"{rule.name!r}: every source in the contract was deleted, yet the reader still "
                        f"produced {filled} -> the reader uses a place not declared in contracts/{platform}.py")


@pytest.mark.parametrize("platform, rule, source", list(_cases("each")))
def test_each_listed_source_is_really_read(request, platform, rule, source):
    fixture_name, to_row = SAMPLES[platform]
    raw = request.getfixturevalue(fixture_name)
    if not _present(raw, rule, source):
        pytest.skip("fixture does not have this source")
    if source in CONDITIONAL:
        pytest.skip(CONDITIONAL[source])
    for other in rule.sources:
        target = _target(other)
        if other == source or source == target or source.startswith((target + ".", target + "[")):
            continue                                  # would delete the kept source too
        _drop(raw, other)
    after = to_row(raw)
    assert any(not _empty(after[f]) for f in rule.feeds), (
        f"{rule.name!r}: only source {source} is left, yet columns {rule.feeds} are empty "
        f"-> the reader does not use this source, remove it from contracts/{platform}.py")


# ---- the rule tables on good data ------------------------------------------------
def test_good_products_break_no_rule(shopee_raw, tiktok_raw):
    for platform, raw in (("shopee", shopee_raw), ("tiktok", tiktok_raw)):
        report = check_file(raw, rules_for(platform, "item"))
        assert not report.broken, report.summary()


def test_good_search_pages_break_no_rule(load):
    shopee_page = {"payload": load("shopee_search_page.json")}
    tiktok_page = {"slug": "giu-nhiet", **parse_keyword_page(load("tiktok_keyword_components.json"))}
    assert not check_file(shopee_page, rules_for("shopee", "search")).broken
    assert not check_file(tiktok_page, rules_for("tiktok", "search")).broken


def test_missing_and_wrong_type_are_reported(shopee_raw):
    del shopee_raw["pdp"]["data"]["item"]["models"]
    shopee_raw["pdp"]["data"]["shop_detailed"]["response_rate"] = "98%"
    report = check_file(shopee_raw, rules_for("shopee", "item"), "x")
    status = {r.name: r.status for r in report.results}
    assert status["Phân loại (SKU)"] == "missing"
    assert status["Tỉ lệ phản hồi shop"] == "wrong_type"
    assert report.broken and "Phân loại (SKU) (thiếu)" in report.summary()


def test_minus_one_is_not_a_price(shopee_raw):
    item = shopee_raw["pdp"]["data"]["item"]
    for key in ("price_min", "price", "price_max"):
        item[key] = -1
    result = {r.name: r for r in check_file(shopee_raw, rules_for("shopee", "item")).results}["Giá bán"]
    assert result.status == "ok" and not result.primary          # served by the variants instead


def test_every_rule_has_a_baseline_entry():
    """Renaming a rule without regenerating the baseline would silently skip the comparison."""
    for platform in ("shopee", "tiktok"):
        for kind in ("item", "search"):
            base = load_baseline(platform, kind)
            assert base, f"missing contracts/baselines/{platform}_{kind}.json"
            names = {r.name for r in rules_for(platform, kind)}
            assert names <= set(base["rules"]), names - set(base["rules"])


# ---- paths -----------------------------------------------------------------------
def test_paths():
    doc = {"a": {"items": [{"p": 1}, {"p": -1}, {"q": 2}], "ids": {"123": {"v": "x"}, "456": {"v": ""}},
                 "deep": {"x": {"attrs": [1]}}, "counts": [10, 1, 2]}}
    assert values_at(doc, "a.items[].p") == [1, -1]
    assert values_at(doc, "a.ids.*.v") == ["x"]                     # "" is not present
    assert values_at(doc, "a.**.attrs") == [[1]]
    assert values_at(doc, "a.counts.0") == [10]
    assert values_at(doc, "a.nothing.here") == []
    delete_at(doc, "a.items[].p")
    assert values_at(doc, "a.items[].p") == []
    delete_at(doc, "a.**.attrs")
    assert values_at(doc, "a.**.attrs") == []


# ---- guard (used while crawling) ----------------------------------------------------
def test_guard_trips_after_n_broken_in_a_row(shopee_raw):
    broken = {"candidate": {}, "pdp": {}}
    guard = SchemaGuard("shopee", "item", limit=3)
    for raw in (broken, broken, shopee_raw, broken, broken):
        guard.observe(raw, "k")
    assert not guard.tripped                        # the good product reset the count
    guard.observe(broken, "k3")
    assert guard.tripped
    assert "check-schema --platform shopee" in guard.message() and "k3" in guard.message()
    guard.reset()
    assert not guard.tripped


def test_guard_can_be_switched_off():
    guard = SchemaGuard("tiktok", "item", limit=0)
    for _ in range(5):
        guard.observe({}, "k")
    assert not guard.tripped


# ---- structure diff with rename hints --------------------------------------------------
def test_renamed_field_is_found_with_its_new_name(shopee_raw):
    n, base = structure([shopee_raw] * 3)
    renamed = copy.deepcopy(shopee_raw)
    rating = renamed["pdp"]["data"]["product_review"]
    rating["rating_summary"] = rating.pop("rating_count")
    renamed["pdp"]["data"]["shop_detailed"]["response_rate"] = "98%"
    n, now = structure([renamed] * 3)
    changes = {(c.kind, c.path): c for c in compare(base, now, n)}
    gone = changes[("gone", "pdp.data.product_review.rating_count")]
    assert gone.hints == ["pdp.data.product_review.rating_summary"]
    assert ("type", "pdp.data.shop_detailed.response_rate") in changes
    assert not any(p.startswith("pdp.data.product_review.rating_count[") for _, p in changes)


def test_run_check_fails_and_names_the_rule(shopee_raw):
    good = [(f"p{i}", copy.deepcopy(shopee_raw)) for i in range(5)]
    baseline = make_baseline(good, "shopee", "item", "test")
    bad = copy.deepcopy(good)
    for _, raw in bad:                                            # Shopee renames the sold counts
        basic, review = raw["candidate"]["basic"], raw["pdp"]["data"]["product_review"]
        basic["sold_v2"] = basic.pop("sold")
        basic["total_sold_v2"] = basic.pop("historical_sold")
        review["total_sold_v2"] = review.pop("historical_sold")
    report = check_section(bad, "shopee", "item", baseline)
    verdict = {r.name: r for r in report.rules}
    assert report.failed
    assert verdict["Đã bán (tổng)"].verdict == "fail" and "5 file thiếu" in verdict["Đã bán (tổng)"].reason
    assert verdict["Bán 30 ngày"].verdict == "fail"
    assert verdict["Giá bán"].verdict == "ok"
    assert not check_section(good, "shopee", "item", baseline).failed


# ---- wired into the crawl ------------------------------------------------------------
class _Page:
    def wait_for_timeout(self, ms):
        pass

    def is_closed(self):
        return False


class _Context:
    pages = [_Page()]


@pytest.mark.parametrize("streak, pauses_expected", [(3, 1), (0, 0)])
def test_crawl_pauses_when_saved_products_stop_matching(tmp_path, monkeypatch, streak, pauses_expected):
    from ecommerce.ingestion.raw_store import RunStore
    from ecommerce.platforms.shopee.extract import detail as D
    from helpers import make_cfg
    pauses = []
    monkeypatch.setattr(D, "human_pause", pauses.append)
    monkeypatch.setattr(D, "jitter_sleep", lambda *a, **k: None)
    # Shopee "changed": the product page answers, but without the fields the tool reads
    monkeypatch.setattr(D, "fetch_product", lambda *a, **k: {"candidate": {}, "pdp": {"data": {}},
                                                             "ratings": [], "shop": []})
    store = RunStore("shopee", "t", root=tmp_path)
    cands = [{"shopid": 1, "itemid": i, "name": "x", "search_rank": i} for i in range(4)]
    cfg = make_cfg(pacing={"long_break_every": 0, "cooldown_every": 0},
                   contracts={"guard_streak": streak})
    D.crawl_details(_Context(), store, cfg, cands)
    assert len(pauses) == pauses_expected
    assert len(list((store.dir / "items").glob("*.json"))) == 4       # still saved: fixable by export
    if pauses:
        assert "đổi cấu trúc JSON" in pauses[0] and "check-schema" in pauses[0]
