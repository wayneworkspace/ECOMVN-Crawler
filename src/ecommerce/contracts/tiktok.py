"""TikTok Shop data contract: the fields the tool reads, and where from.

EDIT THIS FILE WHEN TIKTOK CHANGES. Each rule mirrors one reader in
transform/tiktok/ (file named in `note`); `sources` are listed in the order
that reader tries them. tests/test_contracts.py fails when a rule and its
reader drift apart.

Raw product file  (data/raw/tiktok/<run>/items/<seller>_<product>.json):
    candidate                      the keyword-page card (listing sold, shop name, rating)
    product_info                   component "product_info" of the page's
                                   __MODERN_ROUTER_DATA__ (reviews, shop, categories)
    product_info.product_info.product_model     name, SKUs, stock, images, properties
    product_info.product_info.promotion_model   prices per SKU
Keyword page file  (data/raw/tiktok/<run>/search/page_NNN.json):
    products[]  already cut out of component "feed_list_search_word"
    related[]   slugs of "Related Searches" (the tool walks them)
"""
from ecommerce.contracts.rules import ANY, CORE, DICT, IMPORTANT, LIST, NUMBER, OPTIONAL, TEXT, Expect

C = "product_info"                                   # the component data
M = "product_info.product_info.product_model"        # the product itself
PRICE = "product_info.product_info.promotion_model.promotion_product_price"
REVIEW = "product_info.review_info"
SHOP = "product_info.shop_info"

ITEM_RULES: list[Expect] = [
    # ---- core ------------------------------------------------------------
    Expect(name="Khối dữ liệu sản phẩm", level=CORE, kind=DICT,
           sources=[M],
           note="common.product_model(); extract/tiktok/crawl.py also refuses to save without it."),
    Expect(name="Tên sản phẩm", level=CORE, kind=TEXT, feeds=["title"],
           sources=[f"{M}.name", "candidate.name"],
           note="content.title()"),
    Expect(name="Giá bán", level=CORE, kind=NUMBER, positive=True, feeds=["price_min", "price_max"],
           sources=[f"{PRICE}.skus_price.*.sale_price_decimal", f"{PRICE}.min_price.sale_price_decimal"],
           note="variants.parse_variant() joins prices by skus[].sku_id; price.parse_price() falls back to min_price."),
    Expect(name="Đã bán (tổng)", level=CORE, kind=NUMBER, feeds=["sold_total"],
           sources=[f"{M}.sold_count"],
           note="product.parse_product()"),
    Expect(name="Phân loại (SKU)", level=CORE, kind=LIST, feeds=["variants"],
           sources=[f"{M}.skus"],
           note="variants.parse_variants()"),

    # ---- important ---------------------------------------------------------
    Expect(name="Tồn kho từng SKU", level=IMPORTANT, kind=NUMBER, feeds=["stock_value", "stock_total"],
           sources=[f"{M}.skus[].sku_quantity.available_quantity"],
           note="variants.parse_variant(), stock.parse_stock(): TikTok publishes the stock of every SKU. "
                "(skus[].sku_stock_status only gives in/out of stock, not the number.)"),
    Expect(name="Tình trạng còn / hết hàng", level=IMPORTANT, kind=NUMBER,
           sources=[f"{M}.skus[].sku_stock_status"],
           note="variants.parse_variant(): 1 = in stock, 2 = out. stock.parse_stock() counts it into "
                "'Còn hàng (x/y SKU còn hàng)'. No `feeds`: without this field the text is still "
                "produced from the stock numbers, only wrong -- so only presence is watched."),
    Expect(name="Khuyến mãi", level=OPTIONAL, kind=ANY, feeds=["promotions"],
           sources=[f"{C}.promotion_tag.placement_labels",
                    "product_info.product_info.promotion_model.promotion_logistic_list[].freeShipping",
                    "product_info.product_info.promotion_model.promotion_logistic_list[]."
                    "logisticText.discountViews[].discountDescText"],
           also="discount % computed from sale and original price (price.parse_price)",
           note="content.promotions(): promo labels + shipping vouchers + free shipping."),
    Expect(name="Thương hiệu", level=OPTIONAL, kind=TEXT, feeds=["brand"],
           sources=["candidate.brand"],
           also="the 'Thương hiệu' / 'Brand' row of the attribute table (product_properties)",
           note="content.brand(): the keyword-page card first, then the attribute table."),
    Expect(name="Bảng thuộc tính shop khai", level=IMPORTANT, kind=LIST,
           sources=[f"{M}.product_properties"],
           note="content.properties(): source of 'Địa chỉ shop' (the row 'Địa chỉ tổ chức chịu trách "
                "nhiệm hàng hóa'), origin, warranty, material. No `feeds` because the reader drops "
                "meaningless values (many shops write 'TQ'), so the column can be empty while the field exists."),
    Expect(name="Giá gốc (trước giảm)", level=IMPORTANT, kind=NUMBER, positive=True,
           feeds=["price_before_min", "price_before_max"],
           sources=[f"{PRICE}.skus_price.*.origin_price_decimal", f"{PRICE}.min_price.origin_price_decimal"],
           note="price.parse_price(). Empty is correct for a product that is not discounted."),
    Expect(name="Tên phân loại của SKU", level=IMPORTANT, kind=TEXT,
           sources=[f"{M}.skus[].property_pairs[].sku_property_value_name", f"{M}.skus[].sku_name"],
           note="variants.parse_variant()"),
    Expect(name="Nhóm phân loại", level=IMPORTANT, kind=TEXT, feeds=["tier_names"],
           sources=[f"{M}.sale_properties[].property_name"],
           note="variants.parse_tiers()"),
    Expect(name="Điểm đánh giá", level=IMPORTANT, kind=NUMBER, feeds=["rating_star"],
           sources=[f"{REVIEW}.review_ratings.overall_score", "candidate.rating"],
           note="rating.parse_rating()"),
    Expect(name="Số lượt đánh giá", level=IMPORTANT, kind=NUMBER, feeds=["rating_total"],
           sources=[f"{REVIEW}.review_ratings.review_count", f"{REVIEW}.total_reviews"],
           note="rating.parse_rating()"),
    Expect(name="Phân bố sao (1-5)", level=IMPORTANT, kind=NUMBER, feeds=["rating_5", "rating_1"],
           sources=[f"{REVIEW}.review_ratings.rating_result.*"],
           note="rating.parse_rating(): keys '1'..'5'"),
    Expect(name="Tên shop", level=IMPORTANT, kind=TEXT, feeds=["shop_name"],
           sources=[f"{SHOP}.shop_name", "candidate.shop_name"],
           note="shop.parse_shop()"),
    Expect(name="Tỉ lệ phản hồi shop", level=IMPORTANT, kind=ANY, feeds=["shop_response_rate"],
           sources=[f"{SHOP}.store_sub_score[].score_percentage", f"{SHOP}.desc"],
           note="shop.response_rate(): store_sub_score type 1; fallback: '98% replies' in desc."),
    Expect(name="Ảnh sản phẩm", level=IMPORTANT, kind=LIST, feeds=["images"],
           sources=[f"{M}.images[].url_list"],
           note="content.images()"),
    Expect(name="Mô tả", level=IMPORTANT, kind=TEXT, feeds=["description"],
           sources=[f"{M}.description"],
           note="content.description_text(): a JSON string of text / ul blocks."),
    Expect(name="Bảng thuộc tính", level=IMPORTANT, kind=TEXT, feeds=["attributes_raw"],
           sources=[f"{M}.product_properties[].property_values[].property_value_name"],
           note="content.properties(). Origin, warranty, material and shop address are read from here."),

    # ---- optional ------------------------------------------------------------
    Expect(name="Danh mục", level=OPTIONAL, kind=TEXT, feeds=["category"],
           sources=[f"{C}.categories[].category_name"],
           note="content.category()"),
    Expect(name="Video", level=OPTIONAL, kind=ANY, feeds=["video_count"],
           sources=[f"{M}.videos"],
           note="product.parse_product()"),
]

SEARCH_RULES: list[Expect] = [
    Expect(name="Danh sách sản phẩm", level=CORE, kind=LIST,
           sources=["products"],
           note="listing.parse_keyword_page(): component 'feed_list_search_word'. Some keyword pages "
                "really are empty, so alarm only when several consecutive pages are empty."),
    Expect(name="Mã sản phẩm", level=CORE, kind=NUMBER,
           sources=["products[].product_id"],
           note="listing.listing_hit()"),
    Expect(name="Tên sản phẩm", level=CORE, kind=TEXT,
           sources=["products[].title"],
           note="listing.listing_hit(): the name the drinkware filter runs on"),
    Expect(name="Mã người bán", level=CORE, kind=NUMBER,
           sources=["products[].seller_info.seller_id"],
           note="listing.listing_hit(): needed to name the raw file"),
    Expect(name="Số đã bán (để xếp hạng)", level=CORE, kind=NUMBER,
           sources=["products[].sold_info.sold_count"],
           note="listing.listing_hit(): decides which products get their detail page opened"),
    Expect(name="Trang liên quan", level=IMPORTANT, kind=LIST,
           sources=["related"],
           note="listing.parse_keyword_page(): the tool walks these pages to collect enough products"),
    Expect(name="Giá (thẻ từ khoá)", level=OPTIONAL, kind=NUMBER,
           sources=["products[].product_price_info.sale_price_decimal"],
           note="listing.listing_hit()"),
]
