"""The assignment's field list -> which columns answer it -> how full they are."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Requirement:
    name: str
    keys: tuple[str, ...]        # record keys that answer it (any filled = covered)
    columns: str                 # where to look in the file
    note: str                    # source / platform limitation
    strict: tuple[str, ...] = () # keys of the FULL answer; if these are thin the
                                 # requirement is only partly met even when a
                                 # fallback column is full (e.g. stock status
                                 # without a count)
    strict_label: str = ""


# The assignment's field list, in its own order.
REQUIREMENTS: list[Requirement] = [
    Requirement("Hình ảnh nhiều góc độ", ("images",), "Ảnh 1–3 (nhúng), Link ảnh (tất cả)",
                "Tất cả ảnh trên trang sản phẩm; ảnh từng SKU nhúng ở sheet Detail"),
    Requirement("Brand", ("brand",), "Thương hiệu",
                "Trường brand của sàn / thuộc tính 'Brand'. Shop không khai thì để trống"),
    Requirement("Thông tin sản phẩm", ("title", "description"),
                "Tên, Link, Loại, Thông số shop khai, Mô tả", "Nguyên văn trên trang sản phẩm"),
    Requirement("Kích thước", ("size",), "Kích thước",
                "Bảng thông số, nếu không có thì tìm cm/mm trong mô tả. Nhiều shop không ghi"),
    Requirement("Tính năng", ("features",), "Tính năng",
                "Từ khóa trong tên + thông số + mô tả (giữ nóng/lạnh bao lâu, ống hút, chống tràn...)"),
    Requirement("Giá", ("price_min",), "Giá bán thấp/cao nhất, Giá gốc, % giảm, Giá sau voucher",
                "Giá niêm yết (như nhau với mọi người mua). 'Giá sau voucher' là giá Shopee tự áp voucher, "
                "khác nhau theo tài khoản"),
    Requirement("Số lượng bán trung bình", ("sold_30d",), "Bán 30 ngày (TB tháng)",
                "Số bán 30 ngày gần nhất do Shopee công bố ở trang tìm kiếm"),
    Requirement("Tồn kho", ("stock_value", "stock_state"), "Tồn kho, Tình trạng; sheet Detail: Tồn kho từng SKU",
                "JSON sản phẩm không có số; tool chọn từng SKU và đọc tồn kho (API select_variation / "
                "'pieces available'). Tồn kho = tổng các SKU",
                strict=("stock_total",), strict_label="có tổng tồn kho đầy đủ"),
    Requirement("Địa chỉ shop", ("shop_location",), "Địa chỉ shop",
                "Sàn chỉ công bố tỉnh/thành gửi hàng, không có địa chỉ chi tiết"),
    Requirement("Đánh giá", ("rating_star",), "Điểm đánh giá, Tổng đánh giá, 5 sao → 1 sao",
                "Điểm và phân bố sao là số đầy đủ của sàn. Không xuất nội dung review: trang sản phẩm chỉ "
                "nạp review nổi bật (thử 20 SP: 148/148 review là 5 sao), không đại diện"),
    Requirement("Số lượng đã bán", ("sold_total",), "Đã bán", "Tổng đã bán từ lúc đăng"),
    Requirement("Promotion", ("promotions",), "Khuyến mãi, % giảm, Giá sau voucher",
                "Giảm giá, voucher shop, flash sale, freeship, combo, mua kèm"),
    Requirement("Phân loại", ("variants",), "Số SKU, Phân loại; sheet Detail",
                "Sheet chính ghi số SKU và TÊN NHÓM phân loại (vd 'Màu Sắc / Dịch Vụ'). Chi tiết ở sheet "
                "Detail: mỗi SKU 1 dòng, nhóm phân loại shop đặt giữ nguyên văn (vd Màu Sắc = Xanh bầu trời), "
                "giá, giá gốc, % giảm, còn/hết hàng, ảnh SKU"),
    Requirement("Dung tích", ("capacity",), "Dung tích",
                "Thuộc tính + tên phân loại, nếu không có thì lấy từ tên sản phẩm, quy về ml"),
    Requirement("Chất liệu trong / ngoài", ("material_inner", "material_outer", "material_all"),
                "Chất liệu (trong / ngoài)",
                "Dạng 'Trong: … · Ngoài: …'. Ít shop ghi rõ ruột/vỏ; khi không tách được thì ghi mọi chất "
                "liệu nhắc tới kèm '(không rõ trong/ngoài)'",
                strict=("material_inner", "material_outer"), strict_label="tách được trong/ngoài"),
    Requirement("Màu sắc", ("colors",), "Màu sắc",
                "Tên các lựa chọn trong nhóm phân loại màu (shop hay ghi kèm mẫu/họa tiết). Ô rút gọn còn "
                "5 màu đầu + '(+N màu)' vì trung bình 13,5 màu/sản phẩm; đủ danh sách ở sheet Detail"),
    Requirement("Tỉ lệ phản hồi", ("shop_response_rate",), "Tỉ lệ phản hồi (%)", "Của shop"),
    Requirement("Bảo hành", ("warranty",), "Bảo hành", "Thuộc tính bảo hành hoặc 'bảo hành X tháng' trong mô tả"),
    Requirement("Xuất xứ", ("origin",), "Xuất xứ", "Thuộc tính 'Xuất xứ' hoặc 'made in / xuất xứ' trong mô tả"),
]


def _filled(value: Any) -> bool:
    return value not in (None, "", [], {})


def requirement_coverage(req: Requirement, records: list[dict], strict: bool = False) -> float:
    keys = req.strict if strict and req.strict else req.keys
    if not records:
        return 0.0
    hit = sum(1 for r in records if any(_filled(r.get(k)) for k in keys))
    return hit / len(records)


def coverage_status(ratio: float) -> str:
    if ratio >= 0.9:
        return "✅ Đủ"
    if ratio > 0:
        return "⚠️ Một phần"
    return "❌ Không có"


# ---- TikTok: same requirement list, TikTok-specific source notes --------------
_TIKTOK_NOTES = {
    "Brand": "Trường brand ở trang từ khoá, nếu không có thì thuộc tính 'Thương hiệu'. "
             "Shop ghi 'KHÔNG CÓ' / No brand thì để 'No brand'",
    "Giá": "Giá niêm yết từng SKU sau giảm của shop (promotion_model). Web TikTok không hiện giá sau "
           "voucher nên file không có cột 'Giá sau voucher'",
    "Số lượng bán trung bình": "TikTok Shop web KHÔNG công bố số bán 30 ngày / theo tháng, cũng không có "
                               "ngày đăng sản phẩm để tự chia. Chỉ có tổng đã bán (cột Đã bán)",
    "Tồn kho": "Số chính xác từng SKU có sẵn trong trang sản phẩm (sku_quantity.available_quantity). "
               "Tồn kho = tổng các SKU",
    "Địa chỉ shop": "Web TikTok Shop không có trang cửa hàng (soi trang sản phẩm và trang từ khoá: "
                    "không link nào trỏ tới shop). Chỉ có thuộc tính bắt buộc "
                    "'Địa chỉ tổ chức chịu trách nhiệm hàng hóa'; giữ lại khi nó giống một địa chỉ thật "
                    "(nhiều shop ghi 'TQ' hoặc tên hãng)",
    "Đánh giá": "Điểm, tổng số và phân bố 5→1 sao của sàn (review_ratings)",
    "Số lượng đã bán": "Tổng đã bán hiển thị trên trang sản phẩm; đây cũng là tiêu chí xếp hạng",
    "Promotion": "% giảm, Flash sale / nhãn khuyến mãi, voucher phí ship, miễn phí vận chuyển",
    "Phân loại": "Sheet Detail: mỗi SKU 1 dòng, nhóm phân loại shop đặt giữ nguyên văn, giá, giá gốc, % giảm, "
                 "tồn kho chính xác, ảnh SKU",
    "Tỉ lệ phản hồi": "'% phản hồi tin nhắn trong 24h' của shop (store_sub_score, đúng số TikTok hiển thị)",
}
_TIKTOK_COLUMNS = {
    "Giá": "Giá bán thấp/cao nhất, Giá gốc, % giảm",
    "Số lượng bán trung bình": "— (TikTok không công bố)",
    "Promotion": "Khuyến mãi, % giảm",
}
TIKTOK_REQUIREMENTS = [dataclasses.replace(r, note=_TIKTOK_NOTES.get(r.name, r.note),
                                           columns=_TIKTOK_COLUMNS.get(r.name, r.columns),
                                           strict=() if r.name == "Tồn kho" else r.strict)
                       for r in REQUIREMENTS]


def requirements_for(platform: str) -> list[Requirement]:
    return TIKTOK_REQUIREMENTS if platform == "tiktok" else REQUIREMENTS
