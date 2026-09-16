"""Write the Excel file from a Dataset (list[Product] + excluded + failures + meta).

Sheets
    <Platform>        1 row / product, only the fields the assignment asks for
    Detail            1 row / SKU: SKU picture, the shop's variation groups
                      verbatim, price, discount, stock
    Checklist đề bài  each requirement -> the columns that answer it -> fill
                      rate on this file -> what the platform does not publish
    Bị loại           search results dropped by the filter, with the reason
    Lỗi crawl         products whose page could not be captured
    Thông tin         keyword, sort, run time, counts

Knows nothing about Shopee or TikTok beyond the ReportProfile below.
"""
from __future__ import annotations

import io
import logging
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

import xlsxwriter

from ecommerce.consumption.excel.checklist import coverage_status, requirement_coverage, requirements_for
from ecommerce.consumption.excel.columns import (
    FREEZE_COLUMNS,
    Col,
    SkuCol,
    colors_short,
    material_text,
    sku_image,
    trim_blank_lines,
)
from ecommerce.consumption.excel.layout import ReportLayout
from ecommerce.domain.dataset import Dataset, Excluded
from ecommerce.domain.product import Product
from ecommerce.ingestion.images import fetch_many
from ecommerce.settings import ExportSettings, config_dir, project_home

log = logging.getLogger(__name__)

EXCEL_CELL_LIMIT = 32_000


def load_layout(name: str = "default", root: Path | None = None) -> ReportLayout:
    """`configs/reports/<name>.yaml` -> ReportLayout."""
    path = (Path(root) if root else config_dir()) / "reports" / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"report layout {name!r} not found at {path}")
    return ReportLayout.from_yaml(path)


_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def clean_text(text: str) -> str:
    """Strip control characters from shop-typed names / descriptions.

    Excel's XML does not allow them; xlsxwriter has to write them as '_x0008_'
    and the cell shows that text instead of the character. Seen for real: 1 of
    200 Shopee products had \x08 in its name. Only cleaned when WRITING Excel;
    the raw JSON keeps the original.
    """
    return _CONTROL_CHARS.sub("", text)


class Workbook:
    def __init__(self, path: Path, head_color: str = "#EE4D2D"):
        self.wb = xlsxwriter.Workbook(str(path), {"strings_to_urls": False,
                                                  "nan_inf_to_errors": True})
        wb = self.wb
        self.f = {
            "head": wb.add_format({"bold": True, "text_wrap": True, "valign": "vcenter",
                                   "align": "center", "bg_color": head_color, "font_color": "white",
                                   "border": 1, "border_color": "#D0D0D0"}),
            "text": wb.add_format({"valign": "top"}),
            "wrap": wb.add_format({"valign": "top", "text_wrap": True}),
            "int": wb.add_format({"valign": "top", "num_format": "#,##0"}),
            "money": wb.add_format({"valign": "top", "num_format": "#,##0 \"₫\""}),
            "float": wb.add_format({"valign": "top", "num_format": "0.0#"}),
            "url": wb.add_format({"valign": "top", "font_color": "#1155CC", "underline": 1}),
            "pct": wb.add_format({"valign": "top", "num_format": "0%"}),
            "bold": wb.add_format({"bold": True}),
        }

    def close(self):
        self.wb.close()

    def header(self, ws, cols: list[tuple[str, float]]) -> None:
        ws.set_row(0, 42)
        for c, (title, width) in enumerate(cols):
            ws.write_string(0, c, title, self.f["head"])
            ws.set_column(c, c, width)

    def write_cell(self, ws, row: int, col: int, value: Any, kind: str) -> None:
        if value is None or value == "":
            return
        if kind == "url":
            # write_url refuses >2079-char links and the 65,530th link of a
            # sheet (returns -3 / -4 instead of raising). Keep the text then.
            if ws.write_url(row, col, str(value), self.f["url"], string="Mở link") < 0:
                ws.write_string(row, col, clean_text(str(value))[:EXCEL_CELL_LIMIT], self.f["text"])
        elif kind in ("int", "money", "float"):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                ws.write_number(row, col, value, self.f[kind])
            else:
                ws.write_string(row, col, clean_text(str(value)), self.f["text"])
        else:
            ws.write_string(row, col, clean_text(str(value))[:EXCEL_CELL_LIMIT], self.f["text"])


def to_rows(products: list[Product]) -> list[dict]:
    rows = []
    for p in products:
        row = p.to_row()
        row["material_text"] = material_text(row)
        row["colors_short"] = colors_short(row)
        row["description"] = trim_blank_lines(row.get("description"))
        row["image_links"] = "\n".join(row.get("images") or []) or None
        rows.append(row)
    return rows


def build_workbook(path: Path, products: list[Product], layout: ReportLayout, platform: str, *,
                   excluded: list[Excluded], failures: dict[str, str], meta: dict[str, Any],
                   thumbnails: dict[str, bytes], embedded_images: int = 3, thumbnail_px: int = 110,
                   sku_thumbnails: dict[str, bytes] | None = None, sku_thumbnail_px: int = 70) -> Path:
    """Write the sheets the layout enables, in its order. `products` must
    already be ranked (final_rank set)."""
    rows = to_rows(products)
    style = layout.style(platform)
    book = Workbook(path, style.head_color)
    for sheet in layout.enabled_sheets():
        name = layout.sheet_name(sheet, platform)
        if sheet.type == "products":
            columns: list[Col] = layout.product_columns(sheet, platform)
            freeze = sheet.freeze_columns if sheet.freeze_columns is not None else FREEZE_COLUMNS
            _main_sheet(book, name, rows, thumbnails, embedded_images, thumbnail_px, columns, freeze)
        elif sheet.type == "sku_detail":
            _sku_sheet(book, name, rows, sku_thumbnails or {}, sku_thumbnail_px, layout.sku_columns(sheet, platform))
        elif sheet.type == "checklist":
            _checklist_sheet(book, name, rows, requirements_for(platform))
        elif sheet.type == "excluded":
            _excluded_sheet(book, name, excluded, style.excluded_headers)
        elif sheet.type == "failures":
            _failure_sheet(book, name, failures)
        elif sheet.type == "info":
            _info_sheet(book, name, meta)
    book.close()
    log.info("Wrote %s (%d products)", path, len(rows))
    return path


def report_filename(layout: ReportLayout, dataset: Dataset, prefix: str, stamp: str | None = None) -> str:
    stamp = stamp or datetime.now().strftime("%H%M%S")
    return layout.filename.format(prefix=prefix, platform=dataset.platform, count=len(dataset.products),
                                  run_id=dataset.run_id, stamp=stamp)


def write_report(dataset: Dataset, export: ExportSettings, out_dir: Path | None = None,
                 download_images: bool = True, layout: ReportLayout | None = None,
                 prefix: str | None = None, image_cache: Path | None = None) -> Path:
    """Download thumbnails, name the file, write it.

    One sub-folder per platform (`output/shopee/`, `output/tiktok/`): two
    platforms exported many times into one folder are hard to tell apart.

    Every export is a NEW file (time stamp in the name): Excel with
    AutoSave/OneDrive keeps the old workbook open and silently overwrites the
    file we just wrote.

    `prefix` names the file (domain profile prefix or keyword slug).
    """
    layout = layout or load_layout(export.layout)
    out_dir = out_dir or project_home() / "output"
    image_cache = image_cache or project_home() / "data" / "image_cache"
    top = dataset.products
    embedded = export.embedded_images if download_images else 0
    thumbnails: dict[str, bytes] = {}
    sku_thumbnails: dict[str, bytes] = {}
    if embedded:
        wanted = [u for p in top for u in p.images[:embedded]]
        log.info("Downloading %d thumbnails...", len(wanted))
        thumbnails = fetch_many(wanted, image_cache, export.thumbnail_px)
        rows = [(p.to_row(), v.model_dump()) for p in top for v in p.variants]
        sku_wanted = [u for u in (sku_image(r, v) for r, v in rows) if u]
        log.info("Downloading %d SKU pictures (%d distinct)...", len(sku_wanted), len(set(sku_wanted)))
        sku_thumbnails = fetch_many(sku_wanted, image_cache, export.sku_thumbnail_px)
    folder = out_dir / dataset.platform
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / report_filename(layout, dataset, prefix or dataset.platform)
    return build_workbook(path, top, layout, dataset.platform, excluded=dataset.excluded,
                          failures=dataset.failures, meta=dataset.meta, thumbnails=thumbnails,
                          embedded_images=embedded, thumbnail_px=export.thumbnail_px,
                          sku_thumbnails=sku_thumbnails, sku_thumbnail_px=export.sku_thumbnail_px)


def _main_sheet(book, sheet_name, records, thumbnails, embedded, thumb_px, columns, freeze=FREEZE_COLUMNS):
    ws = book.wb.add_worksheet(sheet_name[:31])

    # Picture cells sit where COLUMNS declares them (kind="image"), no longer by
    # counted position. With embedded_images=2 only the first two picture cells stay.
    plan: list[tuple[str, str, float, Callable[[dict], Any]]] = []
    image_cols: list[int] = []
    for c in columns:
        if c.kind == "image":
            if len(image_cols) >= embedded:
                continue
            image_cols.append(len(plan))
            plan.append((c.header, "image", thumb_px / 7 + 1, lambda r: None))
        else:
            plan.append((c.header, c.kind, c.width, lambda r, k=c.key: r.get(k)))

    book.header(ws, [(h, w) for h, _, w, _ in plan])
    row_height = (thumb_px + 8) * 0.75 if embedded else None
    for row, record in enumerate(records, start=1):
        ws.set_row(row, row_height)
        for col, (_, kind, _, getter) in enumerate(plan):
            if kind != "image":
                book.write_cell(ws, row, col, getter(record), kind)
        urls = record.get("images") or []
        for i, col in enumerate(image_cols):
            data = thumbnails.get(urls[i]) if i < len(urls) else None
            if data:
                ws.insert_image(row, col, f"{record.get('item_id')}_{i}.jpg", {
                    "image_data": io.BytesIO(data), "x_offset": 3, "y_offset": 3,
                    "object_position": 1,   # move and size with cells (sorting keeps images)
                })
    ws.freeze_panes(1, freeze)                           # header + rank / picture / product name
    if records:
        ws.autofilter(0, 0, len(records), len(plan) - 1)


def _sku_value(variant: dict, key: str):
    if key == "discount_pct":
        price, before = variant.get("price"), variant.get("price_before_discount")
        return round(100 * (1 - price / before)) if price and before and before > price else None
    return variant.get(key)


def _tiers(variant: dict) -> list:
    """Variation groups; a model without groups still gets its name shown."""
    tiers = variant.get("tiers") or []
    if not tiers and variant.get("name"):
        return [("Phân loại", variant["name"])]
    return tiers


def _sku_sheet(book, sheet_name, records, thumbnails: dict[str, bytes], thumb_px: int, sku_columns: list[SkuCol]):
    ws = book.wb.add_worksheet(sheet_name[:31])
    rows = [(r, v) for r in records for v in r.get("variants") or []]
    n_tiers = max(2, max((len(_tiers(v)) for _, v in rows), default=0))
    lead = [("Hạng", "int", 6, lambda r, v: r.get("final_rank")),
            ("Tên sản phẩm", "wrap", 30, lambda r, v: r.get("title")),
            ("Ảnh", "image", thumb_px / 7 + 1, lambda r, v: None),
            ("Mã SP", "text", 13, lambda r, v: r.get("item_id")),
            ("Mã SKU", "text", 14, lambda r, v: v.get("model_id"))]
    for t in range(n_tiers):
        lead.append((f"Nhóm phân loại {t + 1}", "text", 13,
                     lambda r, v, t=t: _tiers(v)[t][0] if t < len(_tiers(v)) else None))
        lead.append((f"Giá trị {t + 1}", "text", 20,
                     lambda r, v, t=t: _tiers(v)[t][1] if t < len(_tiers(v)) else None))
    image_col = 2
    book.header(ws, [(h, w) for h, _, w, _ in lead] + [(c.header, c.width) for c in sku_columns])
    row_height = (thumb_px + 6) * 0.75
    for i, (record, variant) in enumerate(rows, start=1):
        ws.set_row(i, row_height)
        for c, (_, kind, _, getter) in enumerate(lead):
            if kind == "image":
                continue
            value = getter(record, variant)
            if kind == "wrap":
                if value:
                    ws.write_string(i, c, clean_text(str(value))[:EXCEL_CELL_LIMIT], book.f["wrap"])
                continue
            book.write_cell(ws, i, c, str(value) if kind == "text" and value is not None else value, kind)
        url = sku_image(record, variant)
        for c, col in enumerate(sku_columns, start=len(lead)):
            book.write_cell(ws, i, c, url if col.key == "image_url" else _sku_value(variant, col.key), col.kind)
        data = thumbnails.get(url) if url else None
        if data:
            # identical pictures (same colour, other size) are stored once by xlsxwriter
            ws.insert_image(i, image_col, f"sku_{variant.get('model_id')}.jpg", {
                "image_data": io.BytesIO(data), "x_offset": 2, "y_offset": 2, "object_position": 1})
    ws.freeze_panes(1, 3)
    if rows:
        ws.autofilter(0, 0, len(rows), len(lead) + len(sku_columns) - 1)


def _checklist_sheet(book, sheet_name, records, requirements):
    ws = book.wb.add_worksheet(sheet_name[:31])
    book.header(ws, [("#", 4), ("Yêu cầu đề bài", 24), ("Cột trong file", 44),
                     (f"Độ phủ ({len(records)} SP)", 11), ("Trạng thái", 12), ("Nguồn / giới hạn", 90)])
    for i, req in enumerate(requirements, start=1):
        ratio = requirement_coverage(req, records)
        note = req.note
        status = coverage_status(ratio)
        if req.strict:
            strict_ratio = requirement_coverage(req, records, strict=True)
            note += f". Chỉ {strict_ratio:.0%} sản phẩm {req.strict_label}."
            if strict_ratio < 0.9 and ratio > 0:
                status = "⚠️ Một phần"
        ws.write_number(i, 0, i)
        ws.write_string(i, 1, req.name, book.f["bold"])
        ws.write_string(i, 2, req.columns, book.f["wrap"])
        ws.write_number(i, 3, ratio, book.f["pct"])
        ws.write_string(i, 4, status)
        ws.write_string(i, 5, note, book.f["wrap"])
    ws.freeze_panes(1, 2)


def _excluded_sheet(book, sheet_name, excluded: list[Excluded], headers: tuple[str, str]):
    ws = book.wb.add_worksheet(sheet_name[:31])
    source_is_text = any(isinstance(e.source, str) for e in excluded)
    book.header(ws, [(headers[0], 9), (headers[1], 22 if source_is_text else 7), ("Tên sản phẩm", 70),
                     ("Loại nhận diện", 22), ("Lý do", 26), ("Link", 12)])
    for i, row in enumerate(excluded, start=1):
        book.write_cell(ws, i, 0, row.rank, "int")
        book.write_cell(ws, i, 1, row.source, "text" if isinstance(row.source, str) else "int")
        book.write_cell(ws, i, 2, row.name, "text")
        book.write_cell(ws, i, 3, row.product_type, "text")
        book.write_cell(ws, i, 4, row.reason, "text")
        book.write_cell(ws, i, 5, row.url, "url")


def _failure_sheet(book, sheet_name, failures):
    ws = book.wb.add_worksheet(sheet_name[:31])
    book.header(ws, [("shopid_itemid", 26), ("Lý do", 100)])
    for i, (key, why) in enumerate(sorted(failures.items()), start=1):
        ws.write_string(i, 0, key)
        ws.write_string(i, 1, why)


def _info_sheet(book, sheet_name, meta):
    ws = book.wb.add_worksheet(sheet_name[:31])
    ws.set_column(0, 0, 34)
    ws.set_column(1, 1, 80)
    meta = {"Xuất file lúc": datetime.now().strftime("%Y-%m-%d %H:%M"), **meta}
    for i, (k, v) in enumerate(meta.items()):
        ws.write_string(i, 0, str(k), book.f["bold"])
        ws.write_string(i, 1, str(v))
