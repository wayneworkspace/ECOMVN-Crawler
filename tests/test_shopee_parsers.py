from ecommerce.platforms.shopee.parse import common as C
from ecommerce.platforms.shopee.parse.listing import select_candidates
from ecommerce.platforms.shopee.parse.product import parse_product
from helpers import PROFILE


def parse(raw, **kw) -> dict:
    """Product model -> the flat record the Excel reads (same keys as before)."""
    return parse_product(raw, PROFILE, **kw).to_row()


def test_price_units_and_hidden():
    assert C.to_price(25_000_000_000) == 250_000
    assert C.to_price(-1) is None
    assert C.to_price(None) is None
    assert C.to_price("8900000000") == 89_000


def test_search_page_dedup_ads_and_filter(load):
    page = load("shopee_search_page.json")
    kept, excluded = select_candidates([(0, page)], target=10, include_ads=False, profile=PROFILE)
    assert [c.itemid for c in kept] == [111, 444]
    # organic rank counts the lunch box (rank 2) but not the ad
    assert [c.search_rank for c in kept] == [1, 3]
    reasons = {c.itemid: c.reason for c in excluded}
    assert "quảng cáo" in reasons[222]
    assert 333 in reasons


def test_search_page_stops_at_target(load):
    kept, _ = select_candidates([(0, load("shopee_search_page.json"))], target=1, include_ads=False, profile=PROFILE)
    assert len(kept) == 1


def test_ads_can_be_included(load):
    kept, _ = select_candidates([(0, load("shopee_search_page.json"))], target=10, include_ads=True, profile=PROFILE)
    assert 222 in [c.itemid for c in kept]


def test_blocked_payload_is_not_an_item(load):
    assert C.pdp_item(load("shopee_pdp_blocked.json")) is None
    assert C.pdp_item(None) is None


def test_parse_product_full(load):
    r = parse(load("shopee_item_raw.json"))
    assert r["item_id"] == 111 and r["shop_id"] == 11
    assert r["url"] == "https://shopee.vn/product/11/111"
    assert r["brand"] == "Lock&Lock"
    assert r["category"] == "Nhà Cửa & Đời Sống > Dụng cụ nhà bếp > Bình giữ nhiệt"
    # price: range from product_price wins over search result
    assert (r["price_min"], r["price_max"]) == (250_000, 290_000)
    assert (r["price_before_min"], r["price_before_max"]) == (320_000, 350_000)
    assert r["discount_pct"] == 22                         # from list prices, not voucher price
    assert r["final_price"] == 224_000                     # product_price = after auto voucher
    # sales: total from pdp, 30 days from search
    assert r["sold_total"] == 36_000 and r["sold_30d"] == 1_200
    assert r["revenue_30d_est"] == 250_000 * 1_200
    assert r["age_months"] and r["sold_per_month_lifetime"] == round(36_000 / r["age_months"])
    assert r["stock_total"] is None                        # Shopee hides the count...
    assert r["stock_value"] is None
    assert r["stock_state"] == "Còn hàng (2/3 SKU còn hàng); sàn ẩn số lượng"
    # rating
    assert r["rating_star"] == 4.87 and r["rating_total"] == 120
    assert (r["rating_5"], r["rating_1"]) == (100, 1)
    assert r["rating_with_media"] == 25
    # specs
    assert r["capacity"] == "500ml, 750ml"
    assert r["capacity_source"] == "thuộc tính + phân loại"
    assert r["material_inner"] == "Inox 316" and r["material_outer"] == "Inox 304"
    assert r["origin"] == "Hàn Quốc" and r["origin_source"] == "thuộc tính"
    assert r["warranty"] == "12 tháng"
    assert r["size"] == "7 x 7 x 25 cm" and r["weight"] == "350g"
    assert r["colors"] == "Đen, Trắng"
    assert "Giữ nóng 12h" in r["features"]
    # shop
    assert r["shop_name"] == "Lock&Lock Official"
    assert r["shop_location"] == "TP. Hồ Chí Minh"
    assert r["shop_response_rate"] == 98 and r["shop_followers"] == 250_000
    assert r["shop_is_mall"] is True
    # promotions
    for label in ("Giá sau voucher tự áp: 224.000đ", "Giảm 22%",
                  "Voucher shop giảm 10% đơn từ 200,000đ", "Freeship"):
        assert label in r["promotions"]
    # media
    assert r["images"][0].endswith("/img111a") and r["image_count"] == 4
    assert r["video_count"] == 1


def test_variants(load):
    r = parse(load("shopee_item_raw.json"))
    v = r["variants"]
    assert r["variant_count"] == 3
    assert v[1] == {"model_id": 2, "tiers": [("Màu sắc", "Đen"), ("Dung tích", "750ml")],
                    "name": "Đen,750ml", "color": "Đen", "capacity": "750ml", "price": 290_000,
                    "price_before_discount": 350_000, "stock": None, "stock_status": "Hết hàng",
                    "sold": 100, "image": C.IMAGE_BASE + "tvA",
                    "final_price": None}   # set only by pass 2 (price after voucher per SKU)
    assert v[2]["color"] == "Trắng" and v[2]["image"].endswith("tvB")


def test_missing_pdp_falls_back_to_search_basic(load):
    raw = load("shopee_item_raw.json")
    raw["pdp"] = {"error": None, "data": {"item": {"item_id": 111, "shop_id": 11}}}
    raw["ratings"] = []
    r = parse(raw)
    assert r["title"].startswith("Bình giữ nhiệt")
    assert r["price_min"] == 250_000
    assert r["sold_total"] == 35_000
    assert r["shop_location"] == "Hà Nội"
    assert r["rating_total"] == 100


def test_low_stock_number_is_shown(load):
    raw = load("shopee_item_raw.json")
    raw["pdp"]["data"]["item"]["stock_display"] = "84"
    r = parse(raw)
    assert r["stock_total"] == 84 and r["stock_value"] == 84


def test_minus_one_price_ranges_are_ignored(load):
    raw = load("shopee_item_raw.json")
    item = raw["pdp"]["data"]["item"]
    for k in ("price", "price_min", "price_max"):
        item[k] = -1
    raw["candidate"]["basic"] = {}
    r = parse(raw)
    assert (r["price_min"], r["price_max"]) == (250_000, 290_000)   # from variants


def test_english_attribute_labels(load):
    raw = load("shopee_item_raw.json")
    raw["pdp"]["data"]["item"]["attributes"] = [
        {"name": "Volume Capacity", "value": "550ml"}, {"name": "Warranty Duration", "value": "6 Months"},
        {"name": "Warranty Type", "value": "Manufacturer Warranty"}, {"name": "Country of Origin", "value": "China"},
        {"name": "Material", "value": "Ceramic, Stainless steel, Inox 316"}]
    raw["pdp"]["data"]["item"]["description"] = ""
    r = parse(raw)
    assert r["capacity"] == "500ml, 550ml, 750ml"
    assert r["warranty"] == "6 tháng - Bảo hành nhà sản xuất"
    assert r["origin"] == "Trung Quốc"
    assert r["material_all"] == "Gốm sứ, Inox 316"


def test_none_not_zero_when_unknown():
    raw = {"candidate": {"itemid": 1, "shopid": 2, "basic": {}},
           "pdp": {"error": None, "data": {"item": {"item_id": 1, "shop_id": 2, "title": "Bình 500ml"}}}}
    r = parse(raw)
    assert r["sold_total"] is None and r["stock_total"] is None and r["revenue_30d_est"] is None
