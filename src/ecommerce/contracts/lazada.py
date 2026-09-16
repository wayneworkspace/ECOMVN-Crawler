"""Lazada data contract: the fields the tool reads, and where from.

EDIT THIS FILE WHEN LAZADA CHANGES. Each rule mirrors one reader in
platforms/lazada/parse/ (named in `note`); `sources` are listed in the order
that reader tries them. The paths below were written from Lazada's public page
structure (`window.__moduleData__.data.root.fields`) and are CONFIRMED / fixed
on the first real probe run -- `ecommerce check-schema --platform lazada` says
which source serves each field.

Raw product file  (data/raw/lazada/<run>/items/<seller>_<item>.json):
    candidate                       the search card (priceShow, itemSoldCntShow, ratingScore, sellerName)
    module_data                     window.__moduleData__ of the product page
    module_data.data.root.fields    product, primaryKey, skuInfos, productOption, review, seller, specifications
    tracking_data                   window.pdpTrackingData (when present)
Search page file  (data/raw/lazada/<run>/search/page_NN.json):
    payload.mods.listItems[]        the cards of `/catalog/?...&ajax=true`
"""
from ecommerce.contracts.rules import CORE, DICT, IMPORTANT, LIST, NUMBER, OPTIONAL, TEXT, Expect

F = "module_data.data.root.fields"
PRODUCT = f"{F}.product"
SKU = f"{F}.skuInfos.*"
OPT = f"{F}.productOption.skuBase"
REVIEW = f"{F}.review.ratings"
SELLER = f"{F}.seller"
CARD = "candidate.basic"

ITEM_RULES: list[Expect] = [
    # ---- core ------------------------------------------------------------
    Expect(name="Khối dữ liệu sản phẩm", level=CORE, kind=DICT,
           sources=[F],
           note="common.LazadaRaw.from_raw(): fields of window.__moduleData__; without it the file is unreadable."),
    Expect(name="Tên sản phẩm", level=CORE, kind=TEXT, feeds=["title"],
           sources=[f"{PRODUCT}.title", f"{PRODUCT}.name", "candidate.name"],
           note="product.title()"),
    Expect(name="Giá bán", level=CORE, kind=NUMBER, positive=True, feeds=["price_min", "price_max"],
           sources=[f"{SKU}.price.salePrice.value", f"{SKU}.price.salePrice", f"{SKU}.salePrice", f"{CARD}.price"],
           note="product.parse_variants() per SKU; parse_price() falls back to the search card."),
    Expect(name="Phân loại (SKU)", level=CORE, kind=DICT, feeds=["variants"],
           sources=[f"{F}.skuInfos"],
           note="product.parse_variants(): one entry per skuId (single-SKU products have one)."),

    # ---- important ---------------------------------------------------------
    Expect(name="Đã bán (tổng)", level=IMPORTANT, kind=NUMBER, feeds=["sold_total"],
           sources=[f"{PRODUCT}.soldCount", "tracking_data.pdt_sold", "tracking_data.pdt_sold_count",
                    f"{REVIEW}.soldCount", f"{CARD}.itemSoldCntShow"],
           note="product.parse_sales(): product page first, else the 'Đã bán 1,2k' text of the search card."),
    Expect(name="Tồn kho từng SKU", level=IMPORTANT, kind=NUMBER, feeds=["stock_value", "stock_total"],
           sources=[f"{SKU}.stock", f"{SKU}.stock.value"],
           note="product.parse_variants()"),
    Expect(name="Giá gốc", level=IMPORTANT, kind=NUMBER, positive=True, feeds=["price_before_min", "discount_pct"],
           sources=[f"{SKU}.price.originalPrice.value", f"{SKU}.price.originalPrice", f"{SKU}.originalPrice",
                    f"{CARD}.originalPrice"],
           note="product.parse_variants(); discount computed from sale / original."),
    Expect(name="Nhóm phân loại", level=IMPORTANT, kind=LIST, feeds=["tier_names"],
           sources=[f"{OPT}.properties"],
           note="product.parse_tiers(): properties[].values[] give option names and pictures."),
    Expect(name="Điểm đánh giá", level=IMPORTANT, kind=NUMBER, feeds=["rating_star"],
           sources=[f"{REVIEW}.average", f"{REVIEW}.averageScore", f"{CARD}.ratingScore"],
           note="product.parse_rating()"),
    Expect(name="Số đánh giá", level=IMPORTANT, kind=NUMBER, feeds=["rating_total"],
           sources=[f"{REVIEW}.rateCount", f"{REVIEW}.count", f"{CARD}.review"],
           note="product.parse_rating()"),
    Expect(name="Tên shop", level=IMPORTANT, kind=TEXT, feeds=["shop_name"],
           sources=[f"{SELLER}.name", f"{CARD}.sellerName"],
           note="product.parse_shop()"),
    Expect(name="Ảnh sản phẩm", level=IMPORTANT, kind=LIST, feeds=["images"],
           sources=[f"{F}.skuGalleries", f"{F}.gallery", f"{PRODUCT}.images", f"{CARD}.image"],
           note="product.images()"),
    Expect(name="Mô tả sản phẩm", level=IMPORTANT, kind=TEXT, feeds=["description"],
           sources=[f"{PRODUCT}.desc", f"{PRODUCT}.highlights", f"{PRODUCT}.description"],
           note="product.description(): HTML stripped to text."),

    # ---- optional ------------------------------------------------------------
    Expect(name="Thông số kỹ thuật", level=OPTIONAL, kind=LIST, feeds=["attributes_raw"],
           sources=[f"{F}.specifications"],
           note="product.attributes(): specifications[].features {key: value}"),
    Expect(name="Thương hiệu", level=OPTIONAL, kind=TEXT, feeds=["brand"],
           sources=[f"{PRODUCT}.brandName", f"{PRODUCT}.brand.name", f"{CARD}.brandName"],
           note="product.brand()"),
    Expect(name="Phân bố sao", level=OPTIONAL, kind=LIST, feeds=["rating_5", "rating_1"],
           sources=[f"{REVIEW}.scores"],
           note="product.parse_rating(): list of 5 counts (order detected) or a dict {star: count}."),
    Expect(name="Địa chỉ shop", level=OPTIONAL, kind=TEXT, feeds=["shop_location"],
           sources=[f"{CARD}.location", f"{F}.sellerInfo.location"],
           note="product.parse_shop()"),
    Expect(name="Tỉ lệ phản hồi", level=OPTIONAL, kind=NUMBER, feeds=["shop_response_rate"],
           sources=[f"{F}.sellerInfo.chatResponseRate", f"{F}.sellerInfo.responseRate"],
           note="product.parse_shop()"),
    Expect(name="Danh mục", level=OPTIONAL, kind=LIST, feeds=["category"],
           sources=[f"{F}.breadcrumb"],
           note="product.category()"),
]

SEARCH_RULES: list[Expect] = [
    Expect(name="Danh sách kết quả", level=CORE, kind=LIST,
           sources=["payload.mods.listItems", "payload.listItems", "payload.data.listItems"],
           note="listing.search_items(): the `ajax=true` JSON of the search page"),
    Expect(name="Mã sản phẩm", level=CORE, kind=NUMBER,
           sources=["payload.mods.listItems[].itemId", "payload.mods.listItems[].nid"],
           note="listing.parse_search_page()"),
    Expect(name="Tên sản phẩm", level=CORE, kind=TEXT,
           sources=["payload.mods.listItems[].name", "payload.mods.listItems[].title"],
           note="listing.parse_search_page(): the name the domain filter runs on"),
    Expect(name="Mã shop", level=IMPORTANT, kind=NUMBER,
           sources=["payload.mods.listItems[].sellerId"],
           note="listing.parse_search_page(): part of the raw file name ('0' when absent)"),
    Expect(name="Mã SKU", level=IMPORTANT, kind=NUMBER,
           sources=["payload.mods.listItems[].skuId", "payload.mods.listItems[].sku"],
           note="listing.parse_search_page(): builds the product URL when itemUrl is absent"),
    Expect(name="Đã bán (thẻ)", level=IMPORTANT, kind=TEXT,
           sources=["payload.mods.listItems[].itemSoldCntShow"],
           note="product.parse_sales() fallback ('Đã bán 1,2k')"),
    Expect(name="Giá (thẻ)", level=OPTIONAL, kind=NUMBER,
           sources=["payload.mods.listItems[].price", "payload.mods.listItems[].priceShow"],
           note="product.parse_price() fallback"),
    Expect(name="Link sản phẩm", level=OPTIONAL, kind=TEXT,
           sources=["payload.mods.listItems[].itemUrl"],
           note="crawl._product_path(): the URL to fetch; else built from itemId + skuId"),
]
