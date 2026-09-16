"""Shopee data contract: the fields the tool reads, and where from.

EDIT THIS FILE WHEN SHOPEE CHANGES. Each rule mirrors one reader in
transform/shopee/ (file named in `note`); `sources` are listed in the order
that reader tries them. tests/test_contracts.py fails when a rule and its
reader drift apart.

Raw product file  (data/raw/shopee/<run>/items/<shop>_<item>.json):
    candidate.basic   the search card  (30-day / total sold live only here)
    pdp.data.item     product page, get_pc  (title, prices, models, ...)
    pdp.data.*        other get_pc blocks: product_price, product_review, shop_detailed ...
    ratings[] / shop[]  extra responses the page loaded (may be empty)
    sku_stock         pass 2 only: stock read by clicking every variation
Search page file  (data/raw/shopee/<run>/search/page_NN.json):
    payload.items[]   one entry per result; Shopee moved the card from
                      item_basic to item_data in 2026 -- the reader takes either
"""
from ecommerce.contracts.rules import ANY, CORE, DICT, IMPORTANT, LIST, NUMBER, OPTIONAL, TEXT, Expect, under

ITEM = "pdp.data.item"       # product block of the product page
DATA = "pdp.data"            # the whole get_pc payload
CARD = "candidate.basic"     # the search card saved with the product
MODELS = [f"{ITEM}.models[]", f"{CARD}.models[]"]
SHOP = [f"{DATA}.shop_detailed", f"{DATA}.shop_info", "shop[].data", "shop[].data.shop_info",
        "shop[].data.shop_detailed"]

ITEM_RULES: list[Expect] = [
    # ---- core: without these the product row is useless ----------------------
    Expect(name="Khối dữ liệu trang sản phẩm", level=CORE, kind=DICT,
           sources=[ITEM],
           note="common.pdp_item(). If gone: every other field can only come from the search card "
                "(no description, attributes or variants)."),
    Expect(name="Tên sản phẩm", level=CORE, kind=TEXT, feeds=["title"],
           sources=[f"{ITEM}.title", f"{ITEM}.name", f"{CARD}.name", "candidate.name"],
           note="content.title()"),
    Expect(name="Giá bán", level=CORE, kind=NUMBER, positive=True, feeds=["price_min", "price_max"],
           sources=[f"{ITEM}.price_min", f"{ITEM}.price_max", f"{ITEM}.price", f"{CARD}.price_min", f"{CARD}.price_max",
                    f"{CARD}.price", *under(MODELS, "price", "price_info.price"),
                    f"{DATA}.product_price.price.range_min", f"{DATA}.product_price.price.single_value"],
           note="price._list_price(). Unit VND x 100000; -1 = not set. product_price is only a "
                "fallback when there is no post-voucher price."),
    Expect(name="Đã bán (tổng)", level=CORE, kind=NUMBER, feeds=["sold_total"],
           sources=[f"{DATA}.product_review.historical_sold", f"{ITEM}.historical_sold", f"{CARD}.historical_sold",
                    f"{CARD}.item_card_display_sold_count.historical_sold_count"],
           note="sales.parse_sales(). Currently only the search card still has this number."),
    Expect(name="Phân loại (SKU)", level=CORE, kind=LIST, feeds=["variants"],
           sources=[f"{ITEM}.models", f"{CARD}.models"],
           note="variants.parse_variants(). A product without variations still has 1 model."),

    # ---- important: most products have them --------------------------------
    Expect(name="Giá gốc (trước giảm)", level=IMPORTANT, kind=NUMBER, positive=True,
           feeds=["price_before_min", "price_before_max"],
           sources=[*under([ITEM, CARD], "price_min_before_discount", "price_max_before_discount",
                                          "price_before_discount"),
                    *under(MODELS, "price_before_discount", "price_info.price_before_discount")],
           note="price._before_discount(). Empty is correct for a product that is not discounted."),
    Expect(name="Bán 30 ngày", level=IMPORTANT, kind=NUMBER, feeds=["sold_30d"],
           sources=[f"{CARD}.item_card_display_sold_count.monthly_sold_count", f"{CARD}.sold", f"{ITEM}.sold"],
           note="sales.parse_sales()"),
    Expect(name="Nhóm phân loại", level=IMPORTANT, kind=LIST, feeds=["tier_names"],
           sources=[f"{ITEM}.tier_variations", f"{CARD}.tier_variations"],
           note="variants.parse_tiers()"),
    Expect(name="Tình trạng còn / hết hàng", level=IMPORTANT, kind=ANY, feeds=["stock_state"],
           sources=[*under(MODELS, "has_stock", "is_grayout"), f"{ITEM}.stock_display",
                    "sku_stock.by_model.*.status"],
           note="variants._stock_status(), stock.parse_stock()"),
    Expect(name="Điểm đánh giá", level=IMPORTANT, kind=NUMBER, feeds=["rating_star"],
           sources=[f"{DATA}.product_review.rating_star", f"{ITEM}.item_rating.rating_star",
                    f"{CARD}.item_rating.rating_star"],
           note="rating.parse_rating()"),
    Expect(name="Số lượt đánh giá", level=IMPORTANT, kind=NUMBER, feeds=["rating_total"],
           sources=[f"{DATA}.product_review.total_rating_count", f"{DATA}.product_review.rating_count.0",
                    f"{ITEM}.item_rating.rating_count.0", f"{CARD}.item_rating.rating_count.0",
                    "ratings[].data.item_rating_summary.rating_count.0",
                    "ratings[].data.item_rating_summary.rating_total", f"{CARD}.cmt_count"],
           note="rating.parse_rating()"),
    Expect(name="Phân bố sao (1-5)", level=IMPORTANT, kind=LIST, feeds=["rating_5", "rating_1"],
           sources=[f"{DATA}.product_review.rating_count", f"{ITEM}.item_rating.rating_count",
                    f"{CARD}.item_rating.rating_count", "ratings[].data.item_rating_summary.rating_count"],
           note="rating.parse_rating(): [total, 1 star, ..., 5 stars]"),
    Expect(name="Tên shop", level=IMPORTANT, kind=TEXT, feeds=["shop_name"],
           sources=[*under(SHOP, "name", "shop_name"), f"{CARD}.shop_name"],
           note="shop.parse_shop()"),
    Expect(name="Địa chỉ shop", level=IMPORTANT, kind=TEXT, feeds=["shop_location"],
           sources=[*under(SHOP, "shop_location", "place"), f"{ITEM}.shop_location", f"{CARD}.shop_location"],
           note="shop.parse_shop()"),
    Expect(name="Tỉ lệ phản hồi shop", level=IMPORTANT, kind=NUMBER, feeds=["shop_response_rate"],
           sources=under(SHOP, "response_rate"),
           note="shop.parse_shop()"),
    Expect(name="Ảnh sản phẩm", level=IMPORTANT, kind=ANY, feeds=["images"],
           sources=[f"{DATA}.product_images.images", f"{ITEM}.images", f"{CARD}.images",
                    f"{ITEM}.image", f"{CARD}.image"],
           note="content.images()"),
    Expect(name="Mô tả", level=IMPORTANT, kind=TEXT, feeds=["description"],
           sources=[f"{ITEM}.description", f"{DATA}.product_description.description",
                    f"{DATA}.product_description.paragraph_list[].text", f"{DATA}.**.paragraph_list[].text"],
           note="content.description()"),
    Expect(name="Bảng thuộc tính", level=IMPORTANT, kind=LIST, feeds=["attributes_raw"],
           sources=[f"{ITEM}.attributes", f"{DATA}.product_attributes.attrs", f"{DATA}.product_attributes.attributes",
                    f"{DATA}.**.attrs"],
           note="content.attributes(): merges ALL sources, not only the first. Capacity, material, "
                "origin and warranty are read from here (transform/specs)."),

    # ---- optional: often empty by nature, only compared with the baseline ----
    Expect(name="Tồn kho (số lượng)", level=OPTIONAL, kind=NUMBER, feeds=["stock_value"],
           sources=["sku_stock.by_model.*.available",
                    *under(MODELS, "stock", "normal_stock", "stock_info.normal_stock"),
                    f"{ITEM}.stock", f"{ITEM}.normal_stock", f"{CARD}.stock"],
           also="item.stock_display when numeric ('84' when nearly sold out)",
           note="variants.merge_sku_stock(), stock.parse_stock(). Shopee hides the quantity; only after pass 2."),
    Expect(name="Giá sau voucher", level=OPTIONAL, kind=NUMBER, positive=True, feeds=["final_price"],
           sources=[f"{DATA}.product_price.price.single_value", f"{DATA}.product_price.price.range_min"],
           note="price.parse_price(): only when product_price.has_final_price is on."),
    Expect(name="Danh mục", level=OPTIONAL, kind=TEXT, feeds=["category"],
           sources=[f"{ITEM}.categories[].display_name", f"{ITEM}.fe_categories[].display_name",
                    f"{CARD}.categories[].display_name"],
           note="content.category()"),
    Expect(name="Thương hiệu", level=OPTIONAL, kind=TEXT, feeds=["brand"],
           sources=[f"{ITEM}.brand", f"{CARD}.brand"],
           also="the 'Thương hiệu' / 'Brand' row of the attribute table",
           note="content.brand()"),
    Expect(name="Ngày đăng bán", level=OPTIONAL, kind=NUMBER, feeds=["listed_date"],
           sources=[f"{ITEM}.ctime", f"{CARD}.ctime"],
           note="sales.parse_sales()"),
    Expect(name="Video", level=OPTIONAL, kind=ANY, feeds=["video_count"],
           sources=[f"{DATA}.product_images.video", f"{ITEM}.video_info_list", f"{CARD}.video_info_list"],
           note="content.video_count()"),
]

# ---- search result pages (which products to open) --------------------------
RESULT = ["payload.items[]", "payload.data.items[]"]       # one search result
RESULT_CARD = [f"{r}.{c}" for r in RESULT for c in ("item_basic", "item_data")]   # the card inside it

SEARCH_RULES: list[Expect] = [
    Expect(name="Danh sách kết quả", level=CORE, kind=LIST,
           sources=["payload.items", "payload.data.items"],
           note="listing.search_items()"),
    Expect(name="Mã sản phẩm", level=CORE, kind=NUMBER,
           sources=[*under(RESULT_CARD, "itemid"), *under(RESULT, "itemid"), *under(RESULT_CARD, "item_id")],
           note="listing.parse_search_page()"),
    Expect(name="Mã shop", level=CORE, kind=NUMBER,
           sources=[*under(RESULT_CARD, "shopid"), *under(RESULT, "shopid"), *under(RESULT_CARD, "shop_id")],
           note="listing.parse_search_page()"),
    Expect(name="Tên sản phẩm", level=CORE, kind=TEXT,
           sources=[*under(RESULT_CARD, "name"), *under(RESULT, "item_card_displayed_asset.name")],
           note="listing.parse_search_page(): the name the drinkware filter runs on"),
    Expect(name="Bán 30 ngày", level=IMPORTANT, kind=NUMBER,
           sources=[*under(RESULT_CARD, "item_card_display_sold_count.monthly_sold_count", "sold")],
           note="saved into candidate.basic -> sales.parse_sales()"),
    Expect(name="Đã bán (tổng)", level=IMPORTANT, kind=NUMBER,
           sources=[*under(RESULT_CARD, "item_card_display_sold_count.historical_sold_count", "historical_sold")],
           note="saved into candidate.basic -> sales.parse_sales()"),
]
