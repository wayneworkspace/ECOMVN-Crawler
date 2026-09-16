"""The column registry: which fields become which Excel columns.

Keys are `Product.to_row()` keys (plus a few derived ones computed in
`excel.to_rows`). The registry defines header, width and cell kind; WHICH
columns appear, and in what order, is decided by the report layout YAML
(`configs/reports/<name>.yaml`, see layout.py). Everything listed here is
available to a layout; a layout that lists nothing gets everything, in this order.
"""
from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Col:
    key: str
    header: str
    width: float = 14
    kind: str = "text"   # text|int|money|float|url|long|date|image

    def with_overrides(self, header: str | None = None, width: float | None = None) -> Col:
        return replace(self, header=header or self.header, width=width or self.width)


@dataclass(frozen=True)
class SkuCol:
    key: str
    header: str
    kind: str = "text"
    width: float = 12

    def with_overrides(self, header: str | None = None, width: float | None = None) -> SkuCol:
        return replace(self, header=header or self.header, width=width or self.width)


# Main sheet, in 7 reading blocks: identity -> price -> sales & stock -> rating
# -> attributes -> shop -> raw data (long, rarely read, kept last).
#
# Embedded picture cells are declared RIGHT IN this list (kind="image"), no
# longer inserted by hand-counted position: reordering columns cannot make a
# picture land in another column. The number of picture cells actually shown =
# export.embedded_images, taken in the order declared here.
COLUMNS: list[Col] = [
    # --- identity (panes frozen up to "Tên sản phẩm") ---
    Col("final_rank", "Hạng", 6, "int"),
    Col("image_1", "Ảnh 1", 14, "image"),
    Col("title", "Tên sản phẩm", 45),
    Col("url", "Link sản phẩm", 12, "url"),
    Col("item_id", "Mã SP", 13),
    Col("product_type", "Loại sản phẩm", 11),
    Col("brand", "Thương hiệu", 14),
    # --- price ---
    Col("price_min", "Giá bán thấp nhất", 13, "money"),
    Col("price_max", "Giá bán cao nhất", 13, "money"),
    Col("price_before_min", "Giá gốc", 13, "money"),
    Col("discount_pct", "% giảm", 7, "int"),
    Col("final_price", "Giá sau voucher", 13, "money"),
    # --- sales & stock ---
    Col("sold_total", "Đã bán", 10, "int"),
    Col("sold_30d", "Bán 30 ngày (TB tháng)", 11, "int"),
    Col("stock_value", "Tồn kho", 10, "int"),
    Col("stock_state", "Tình trạng", 30),
    # --- rating ---
    Col("rating_star", "Điểm đánh giá", 8, "float"),
    Col("rating_total", "Tổng đánh giá", 9, "int"),
    Col("rating_5", "5 sao", 7, "int"),
    Col("rating_4", "4 sao", 7, "int"),
    Col("rating_3", "3 sao", 7, "int"),
    Col("rating_2", "2 sao", 7, "int"),
    Col("rating_1", "1 sao", 7, "int"),
    # --- attributes (per-SKU detail lives on the Detail sheet) ---
    Col("variant_count", "Số SKU", 7, "int"),
    Col("tier_names", "Phân loại", 22),
    Col("capacity", "Dung tích", 14),
    Col("material_text", "Chất liệu (trong / ngoài)", 26),
    Col("colors_short", "Màu sắc", 34),
    Col("features", "Tính năng", 30),
    Col("origin", "Xuất xứ", 11),
    Col("size", "Kích thước", 18),
    Col("warranty", "Bảo hành", 16),
    # --- shop ---
    Col("shop_name", "Tên shop", 18),
    Col("shop_joined", "Ngày mở shop", 12, "date"),
    Col("shop_url", "Link shop", 10, "url"),
    Col("shop_location", "Địa chỉ shop", 16),
    Col("shop_response_rate", "Tỉ lệ phản hồi (%)", 9, "int"),
    # --- raw data: long cells, rarely read ---
    Col("promotions", "Khuyến mãi", 34),
    Col("attributes_raw", "Thông số shop khai", 40, "long"),
    Col("description", "Mô tả sản phẩm", 50, "long"),
    Col("image_links", "Link ảnh (tất cả)", 40, "long"),
    Col("image_2", "Ảnh 2", 12, "image"),
    Col("image_3", "Ảnh 3", 12, "image"),
]

# Frozen columns: rank + picture + product name stay visible when scrolling right.
FREEZE_COLUMNS = 3

# Detail sheet: one row per SKU (Shopee model), laid out as the user's target
# file: Hạng | Tên | Ảnh | Mã SP | Mã SKU | groups... | numbers | Link ảnh.
# The shop's variation groups are copied verbatim ("Màu Sắc" = "Xanh bầu trời").
SKU_COLUMNS: list[SkuCol] = [
    SkuCol("capacity", "Dung tích", "text", 10),
    SkuCol("price", "Giá", "money", 12),
    SkuCol("price_before_discount", "Giá gốc", "money", 12),
    SkuCol("discount_pct", "% giảm", "int", 7),
    SkuCol("final_price", "Giá sau voucher", "money", 12),
    SkuCol("stock", "Tồn kho (pieces available)", "int", 12),
    SkuCol("stock_status", "Tình trạng", "text", 11),
    SkuCol("image_url", "Link Ảnh", "url", 10),
]


def material_text(record: dict) -> str | None:
    """Inner / outer / everything else, in one cell."""
    inner, outer = record.get("material_inner"), record.get("material_outer")
    all_names = [m.strip() for m in (record.get("material_all") or "").split(",") if m.strip()]
    if not inner and not outer:
        return f"{', '.join(all_names)} (không rõ trong/ngoài)" if all_names else None
    parts = []
    if inner:
        parts.append(f"Trong: {inner}")
    if outer:
        parts.append(f"Ngoài: {outer}")
    rest = [m for m in all_names if m not in (inner, outer)]
    if rest:
        parts.append(f"Khác: {', '.join(rest)}")
    return " · ".join(parts)


def colors_short(record: dict, keep: int = 5) -> str | None:
    """First 5 colours + "(+N màu)". The full list averages 13.5 colours and the
    longest is 1,330 characters -- unreadable in one cell. Every SKU already
    has its own on the Detail sheet."""
    parts = [p.strip() for p in str(record.get("colors") or "").split(",") if p.strip()]
    if not parts:
        return None
    if len(parts) <= keep:
        return ", ".join(parts)
    return ", ".join(parts[:keep]) + f"  (+{len(parts) - keep} màu)"


def trim_blank_lines(text: str | None) -> str | None:
    """Shops often start a description with a dozen blank lines; the Excel cell
    then shows only whitespace."""
    if not text:
        return text
    lines = [d.rstrip() for d in str(text).splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) or None


def sku_image(row: dict, variant: dict) -> str | None:
    """The SKU's own picture (shown next to its option on the site), else the cover."""
    return variant.get("image") or next(iter(row.get("images") or []), None)
