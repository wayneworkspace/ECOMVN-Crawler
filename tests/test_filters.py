import pytest

from ecommerce.transformation.filters import classify
from helpers import PROFILE


@pytest.mark.parametrize("title, keep, kind", [
    ("Bình giữ nhiệt 500ml tặng túi", True, "Bình"),
    ("Túi giữ nhiệt đựng bình sữa", False, "Túi"),
    ("Hộp cơm giữ nhiệt kèm bình nước", False, "Hộp cơm / hộp đựng"),
    ("Ly giữ nhiệt ô tô 900ml có ống hút", True, "Ly"),
    ("Cốc giữ nhiệt báo nhiệt độ LED", True, "Cốc"),          # 'áo' inside 'báo'
    ("Tất cả mẫu ly giữ nhiệt", True, "Ly"),                  # 'tất' in 'tất cả'
    ("Set hộp quà bình giữ nhiệt khắc tên", True, "Bình"),     # gift box != lunch box
    ("Áo giữ nhiệt nam lót lông", False, "Quần áo giữ nhiệt"),
    ("Nắp bình giữ nhiệt thay thế", False, "Phụ kiện"),
    ("Phích giữ nhiệt Rạng Đông 2L", True, "Phích"),
    ("Stanley Quencher 1.18L chính hãng", True, "Bình / ly (không rõ)"),
    ("Miếng dán giữ nhiệt", False, "Miếng dán / túi chườm"),
])
def test_classify(title, keep, kind):
    verdict = classify(title, PROFILE)
    assert verdict.keep is keep
    assert verdict.product_type == kind


def test_unknown_without_capacity_is_dropped_but_explained():
    verdict = classify("Lock&Lock LHC giữ nhiệt", PROFILE)
    assert not verdict.keep and verdict.reason


@pytest.mark.parametrize("title,keep", [
    # real TikTok top sellers (11/09): the gift tag comes first
    ("[Tặng Túi Canvas Khi Khắc Tên] Ly giữ nhiệt Candy inox 316 cao cấp", True),
    ("<Tặng Túi Giữ Nhiệt> Bình Giữ Nhiệt 1000ml Inox 316 NIUMI", True),
    ("TẶNG KÈM DÂY ĐEO Bình giữ nhiệt inox 316 cao cấp 900ml", True),
    ("[combo 7 phụ kiện]Ly giữ nhiệt 750 ml có kèm phụ kiện 1 ống hút", True),
    ("[Bình giữ nhiệt 1L]", True),
    # still dropped
    ("Phụ kiện ly giữ nhiệt - Nắp, Túi, Ống Hút, Cọ", False),
    ("Túi đựng bình giữ nhiêt NATOLI", False),
    ("[XẢ HÀNG] Áo giữ nhiệt nam", False),
    ("( Tặng Khay Hâm)  Ấm đun nước pha sữa Tootie", False),
    ("Bình ủ cháo, giữ nhiệt lõi inox 304 TEDEMEI dùng mang cháo", False),
    ("Bình đựng thức ăn giữ nhiệt inox 304 Elmich EL8336", False),
    ("Bình giữ nhiệt inox 304 kèm cốc uống nước", True),
])
def test_freebie_tags_do_not_decide_the_type(title, keep):
    assert classify(title, PROFILE).keep is keep
