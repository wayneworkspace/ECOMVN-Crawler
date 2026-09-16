from ecommerce.transformation import specs as A


def test_capacity_units_normalised_to_ml():
    assert A.capacities_ml("Bình 1.2L và 500ML, ly 20oz") == [1200, 500, 591]
    assert A.capacities_ml("1,5 lít") == [1500]
    assert A.capacities_ml("model 3000L xyz") == []          # out of range -> noise


def test_capacity_merges_table_and_variants_ignores_title():
    found = A.extract_capacity({"Dung tích": "750ml"}, ["500ml"], "Bình 1L", "")
    assert found.value == "500ml, 750ml" and found.source == "thuộc tính + phân loại"


def test_capacity_falls_back_to_variants_then_title():
    found = A.extract_capacity({}, ["Đen - 500ml", "Đen - 1L"], "Bình", "")
    assert found.value == "500ml, 1000ml" and found.extra == {"min_ml": 500, "max_ml": 1000}
    assert A.extract_capacity({}, [], "Ly 900ml", "").source == "tiêu đề"


def test_materials_inner_outer():
    m = A.extract_materials({}, "", "Ruột inox 316 an toàn, vỏ ngoài inox 304 sơn tĩnh điện")
    assert m["inner"].value == "Inox 316"
    assert m["outer"].value == "Inox 304"
    assert "Sơn tĩnh điện" in m["all"].value


def test_materials_ignore_please_contact_boilerplate():
    m = A.extract_materials({}, "", "Vui lòng liên hệ shop. Chất liệu nhựa PP")
    assert m["inner"].value is None
    assert m["all"].value == "Nhựa PP"


def test_ceramic_inner_coating():
    m = A.extract_materials({}, "Ly giữ nhiệt lòng sứ 600ml", "")
    assert m["inner"].value == "Gốm sứ"


def test_origin():
    assert A.extract_origin({"Xuất xứ": "China"}, "", "").value == "Trung Quốc"
    assert A.extract_origin({}, "", "Hàng Made in Japan chính hãng").value == "Nhật Bản"
    assert A.extract_origin({}, "", "không có gì").value is None


def test_warranty():
    assert A.extract_warranty({}, "", "Bảo hành 12 tháng").value == "12 tháng"
    assert A.extract_warranty({}, "", "Bảo hành trọn đời").value == "Trọn đời"
    assert A.extract_warranty({}, "", "1 đổi 1 trong 7 ngày").value == "Đổi trả 7 ngày"
    assert A.extract_warranty({"Thời hạn bảo hành": "6 tháng", "Loại bảo hành": "Nhà sản xuất"},
                              "", "").value == "6 tháng - Nhà sản xuất"


def test_size_and_weight():
    assert A.extract_size({}, "", "Kích thước: 7 x 7 x 25 cm").value == "7 x 7 x 25 cm"
    assert A.extract_size({}, "", "Chiều cao 25cm, đường kính 7cm").value == "chiều cao 25cm; đường kính 7cm"
    assert A.extract_weight({}, "Trọng lượng 350g").value == "350g"


def test_features():
    f = A.extract_features("Cốc có ống hút", "Giữ nóng đến 12 giờ, giữ lạnh 24h. Nắp bật chống tràn, không chứa BPA")
    for label in ("Giữ nóng 12h", "Giữ lạnh 24h", "Có ống hút", "Nắp bật", "Chống tràn", "Không BPA"):
        assert label in f.value


def test_colors_from_tier_named_color():
    tiers = [{"name": "Màu sắc", "options": ["Đen", "Hồng pastel"]}, {"name": "Size", "options": ["500ml"]}]
    assert A.extract_colors(tiers, {}, "").value == "Đen, Hồng pastel"


def test_colors_guessed_from_options():
    tiers = [{"name": "Phân loại", "options": ["Xanh 500ml", "Đỏ 500ml", "Combo 2"]}]
    assert A.extract_colors(tiers, {}, "").value == "Xanh 500ml, Đỏ 500ml"
