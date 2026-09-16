"""Lazada parsers on a synthetic raw file shaped like window.__moduleData__.
The fixture follows Lazada's public page structure; the first real probe run
confirms or corrects the paths (see contracts/lazada.py)."""
import pytest

from ecommerce.contracts import check_file, rules_for
from ecommerce.ingestion.raw_store import RunStore, write_json
from ecommerce.platforms.lazada.parse import common as C
from ecommerce.platforms.lazada.parse.listing import parse_search_page, select_candidates
from ecommerce.platforms.lazada.parse.product import parse_product
from helpers import PROFILE_OIL, make_cfg


@pytest.fixture
def raw(load):
    return load("lazada_pdp_raw.json")


@pytest.fixture
def search(load):
    return load("lazada_search_page.json")


def test_number_helpers():
    assert C.to_int("129.000 ₫") == 129000 and C.to_int("1,234,000") == 1234000 and C.to_int(4.0) == 4
    assert C.to_int("22% Off") == 22 and C.to_int("abc") is None and C.to_int(True) is None
    assert C.sold_count("Đã bán 1,2k") == 1200 and C.sold_count("856 đã bán") == 856
    assert C.sold_count("3.4K sold") == 3400 and C.sold_count(None) is None and C.sold_count(15) == 15
    assert C.strip_html("<p>a<br>b</p><ul><li>c</li></ul>") == "a\nb\nc"


def test_search_page_and_candidates(search):
    hits = parse_search_page(search)
    assert [h.item_id for h in hits] == ["1230376943", "222", "333", "444"]
    assert hits[3].is_ad and not hits[0].is_ad
    kept, excluded = select_candidates([(0, search)], target=10, include_ads=False, profile=PROFILE_OIL)
    assert [c.item_id for c in kept] == ["1230376943", "222"]
    assert [c.search_rank for c in kept] == [1, 2]
    reasons = {c.item_id: c.reason for c in excluded}
    assert reasons["444"] == "quảng cáo" and "Lọc" in reasons["333"]
    assert kept[0].key == "100200_1230376943"


def test_parse_product_core_fields(raw):
    p = parse_product(raw, PROFILE_OIL)
    row = p.to_row()
    assert p.platform == "lazada" and p.item_id == "1230376943"
    assert p.title.startswith("Dầu nhớt xe tay ga 800ml")
    assert p.brand == "Idemitsu" and p.category == "Ô tô - Xe máy > Dầu nhớt xe máy"
    assert (row["price_min"], row["price_max"], row["price_before_min"], row["discount_pct"]) == (129000, 245000, 165000, 22)
    assert row["sold_total"] == 1200 and row["listing_sold"] == 1200
    assert row["rating_star"] == 4.8 and row["rating_total"] == 356 and row["rating_5"] == 300 and row["rating_1"] == 2
    assert row["shop_name"] == "Idemitsu Official Store" and row["shop_location"] == "Hồ Chí Minh"
    assert row["shop_is_mall"] is True and row["shop_response_rate"] == 92 and row["shop_ship_48h"] == 99
    assert row["images"] == ["https://img.lazcdn.com/a.jpg", "https://img.lazcdn.com/b.jpg"]
    assert row["url"] == "https://www.lazada.vn/products/dau-nhot-i1230376943-s4564299902.html"
    assert "Thương hiệu: Idemitsu" in row["attributes_raw"] and "Bảo hành 12 tháng" in row["description"]
    assert "Nhớt bán tổng hợp" in row["description"]          # highlights + desc, HTML stripped


def test_parse_product_variants_and_stock(raw):
    p = parse_product(raw, PROFILE_OIL)
    assert p.tier_names == "Dung tích"
    v1, v2 = p.variants
    assert v1.model_id == "4564299902" and v1.name == "0.8L" and v1.tiers == [("Dung tích", "0.8L")]
    assert (v1.price, v1.price_before_discount, v1.stock, v1.stock_status) == (129000, 165000, 57, "Còn hàng")
    assert v1.image == "https://img.lazcdn.com/v1.jpg" and v1.capacity == "800ml"
    assert v2.stock == 0 and v2.stock_status == "Hết hàng"
    assert p.stock.total == 57 and p.stock.state == "Còn hàng (1/2 SKU còn hàng)"


def test_parse_product_domain_attributes(raw):
    row = parse_product(raw, PROFILE_OIL).to_row()
    assert row["capacity"] == "800ml, 1600ml"
    assert row["attr_grade"] == "10W-30" and row["attr_jaso"] == "MB" and row["attr_api"] == "SL"
    assert "attr_type" not in row                  # `type` is a title-only group and the title names none


def test_single_sku_product_without_options(raw):
    fields = raw["module_data"]["data"]["root"]["fields"]
    del fields["productOption"]
    fields["skuInfos"] = {"4564299902": fields["skuInfos"]["4564299902"]}
    p = parse_product(raw)
    assert len(p.variants) == 1 and p.variants[0].price == 129000 and p.variants[0].name is None
    assert p.price.min == 129000 and p.product_type is None


def test_falls_back_to_the_search_card(raw):
    raw["module_data"] = {"data": {"root": {"fields": {"product": {"title": "x"}}}}}
    p = parse_product(raw)
    assert p.price.min == 129000 and p.sales.total == 1200 and p.rating.star == 4.8
    assert p.shop.name == "Idemitsu Official Store" and p.images == ["https://img.lazcdn.com/a.jpg"]


def test_contract_matches_the_fixture(raw, search):
    assert not check_file(raw, rules_for("lazada", "item"), "fixture").broken
    assert not check_file({"payload": search}, rules_for("lazada", "search"), "page").broken
    assert not C.is_valid_product({"candidate": {}, "module_data": {}})


def test_dataset_and_export(tmp_path, raw, search, monkeypatch):
    import openpyxl

    from ecommerce.consumption.excel.excel import load_layout, write_report
    from ecommerce.platforms.lazada.parse.dataset import build_dataset
    store = RunStore("lazada", "t1", root=tmp_path)
    write_json(store.search_path(0), {"payload": search})
    kept, excluded = select_candidates([(0, search)], target=10, include_ads=False, profile=PROFILE_OIL)
    write_json(store.candidates_path, {"keyword": "dầu nhớt xe máy", "kept": [c.dump() for c in kept],
                                       "excluded": [c.dump() for c in excluded]})
    write_json(store.item_path("100200", "1230376943"), raw)
    cfg = make_cfg("lazada", profile=PROFILE_OIL, lazada={"target": 200})
    dataset = build_dataset(store, cfg)
    assert [p.final_rank for p in dataset.products] == [1] and len(dataset.excluded) == 2
    assert dataset.meta["Sàn"].startswith("Lazada")
    path = write_report(dataset, cfg.export, out_dir=tmp_path, download_images=False,
                        layout=load_layout("dau_nhot_xe_may"), prefix="dau_nhot_xe_may")
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["Lazada", "Detail", "Bị loại", "Lỗi crawl", "Thông tin"]
    headers = [c.value for c in wb["Lazada"][1]]
    assert "Cấp nhớt" in headers and "JASO" in headers and "API" in headers
    assert "Giá sau voucher" not in headers and "Bán 30 ngày (TB tháng)" not in headers
