\# Shopee Analysis Checklist — Bài tập bình giữ nhiệt



Mục đích làm rõ đề bài trước khi viết code, và thu đủ bằng chứng

để chốt schema từ thực tế thay vì từ mong muốn.



Đi kèm `planningShopee\_TikTok\_Crawl\_Planning.md` (bản điền 8 mục template).



Quy tắc không mở editor cho tới khi xong Phần 2.



\---



\## Phần 0 — Trước khi mở Shopee (30 phút)



\- \[ ] Đọc lại `TemplateWeb\_Crawl\_Planning\_Template.md`, mục 1 và mục 3

\- \[ ] Gửi mentor bản kế hoạch, ghi rõ đang khảo sát song song, không ngồi chờ

\- \[ ] Hỏi ngay 2 câu chặn deadline và có ngân sách mua API không

\- \[ ] Ba câu còn lại để mentor trả lời sau, không chặn tiến độ

\- \[ ] Tạo file `survey.xlsx` với cấu trúc ở Phần 2 dưới đây



Vì sao chỉ hỏi ngay 2 câu hai câu đó nếu trả lời khác đi sẽ làm vô hiệu

hoá công sức. Deadline quyết định phạm vi; ngân sách quyết định tự viết

crawler hay mua dữ liệu. Ba câu còn lại chỉ định hướng chi tiết.



\---



\## Phần 1 — Khảo sát từ khoá (1 giờ)



\- \[ ] Tìm `giữ nhiệt` trên Shopee, sắp xếp Bán chạy

\- \[ ] Xem 3 trang đầu, khoảng 180 kết quả

\- \[ ] Đếm thô mỗi nhóm xuất hiện bao nhiêu bình  ly  phích  hộp cơm  bình bé  phụ kiện

\- \[ ] Ghi lại tỷ lệ nhiễu, ví dụ 60% là bình, 25% ly, 15% khác

\- \[ ] Thử thêm 2 từ khoá `bình giữ nhiệt`, `bình nước giữ nhiệt`

\- \[ ] So kết quả từ khoá nào cho tỷ lệ nhiễu thấp nhất

\- \[ ] Ghi lại số kết quả mỗi từ khoá trả về



Đầu ra một đoạn ngắn đề xuất từ khoá nào nên dùng, kèm số liệu.

Đây là bằng chứng để mentor chốt tiêu chí, không phải cảm tính.



\---



\## Phần 2 — Khảo sát 20 sản phẩm bằng tay (2–3 giờ)



Bước quan trọng nhất. Bỏ qua bước này rất dễ code hai tuần rồi

phát hiện field cần không tồn tại.



Chọn mẫu 20 sản phẩm, cố ý đa dạng

\- \[ ] 5 sản phẩm bán chạy nhất

\- \[ ] 5 sản phẩm giá cao (trên 500k)

\- \[ ] 5 sản phẩm giá thấp (dưới 150k)

\- \[ ] 5 sản phẩm mới hoặc ít đánh giá



Cấu trúc `survey.xlsx` mỗi dòng một field, mỗi cột một sản phẩm.



&#x20;Field  SP1  SP2  ...  SP20  Có  20  Ghi chú 

\---------------------

&#x20;tên sản phẩm  ✓  ✓   ✓  20  luôn có 

&#x20;brand  ✗  ✓   ✗  7  nhiều shop bỏ trống 

&#x20;tồn kho  ...      



Danh sách field cần kiểm tra (theo đề bài của mentor)



\- \[ ] Định danh tên, item\_id, url, brand

\- \[ ] Giá giá hiện tại, giá gốc, % giảm

\- \[ ] Nhu cầu đã bán, tồn kho

\- \[ ] Chất lượng rating, số đánh giá, số hỏi đáp

\- \[ ] Phân loại các biến thể, giá riêng từng biến thể

\- \[ ] Thuộc tính dung tích, kích thước, chất liệu trong, chất liệu ngoài

\- \[ ] Thuộc tính màu sắc, tính năng, xuất xứ, bảo hành

\- \[ ] Media số lượng ảnh, có video không

\- \[ ] Shop tên, địa chỉ, tỉ lệ phản hồi, người theo dõi, đánh giá shop

\- \[ ] Khuyến mãi voucher, combo, freeship



Với mỗi field ghi 3 thứ

1\. Có xuất hiện không

2\. Nằm ở đâu trên trang (khối nào)

3\. Định dạng gì (số, chữ, danh sách, text tự do)



Cột `Có  20` chính là cột `status` trong `fields.yaml`

\- 18–20 → `have`

\- 6–17 → `have(x%)`, dùng được nhưng phải báo độ phủ

\- 1–5 → `skip`, độ phủ quá thấp để phân tích

\- 0 → báo mentor là sàn không công bố



\---



\## Phần 3 — Khảo sát kỹ thuật (1 giờ)



\- \[ ] Mở DevTools, tab Network, lọc XHRFetch

\- \[ ] Tải lại một trang sản phẩm, xem request nào trả JSON

\- \[ ] Mở JSON đó ra, so với danh sách field ở Phần 2

\- \[ ] Ghi lại JSON có sẵn bao nhiêu field trong số cần lấy

\- \[ ] Xem header của request có token, chữ ký, cookie đặc biệt không

\- \[ ] Thử tải lại 10 lần liên tiếp, xem có bị chặn hay CAPTCHA không

\- \[ ] Ghi lại sau bao nhiêu request thì bị chặn



Đầu ra kết luận nên đi hướng nào — đọc JSON từ API nội bộ,

hay bóc DOM bằng Playwright. Kèm ước lượng độ khó có căn cứ.



Lưu ý làm nhẹ tay, vài chục request là đủ để đánh giá.

Không cần và không nên thử tới lúc bị khoá.



\---



\## Phần 4 — Chốt phạm vi (30 phút)



\- \[ ] Từ Phần 1, đề xuất từ khoá và tiêu chí lọc sản phẩm

\- \[ ] Từ Phần 2, cắt danh sách field bỏ những field độ phủ dưới 30%

\- \[ ] Từ Phần 3, đề xuất công cụ và ước lượng thời gian

\- \[ ] Tính lại tổng số dòng dự kiến

\- \[ ] Kiểm tra mỗi phân khúc có đạt tối thiểu 20 mẫu không



\---



\## Phần 5 — Viết lại kế hoạch (1 giờ)



\- \[ ] Cập nhật `planningShopee\_TikTok\_Crawl\_Planning.md`

\- \[ ] Thay mọi `\[KHẢO SÁT]` bằng số liệu thật từ Phần 2

\- \[ ] Điền câu one-line brief cho hết chỗ trống

\- \[ ] Viết `configfields.yaml` với cột `status` đã có bằng chứng

\- \[ ] Viết `configcrawl\_scope.yaml` từ khoá, cách sắp xếp, số trang

\- \[ ] Gửi mentor bản cập nhật, kèm bảng khảo sát 20 sản phẩm



\---



\## Phần 6 — Chỉ sau khi mentor duyệt mới code



\- \[ ] Copy cấu trúc từ dự án Amazon `config`, `src`, `dataraw`

\- \[ ] Dùng lại `parsers.py`, `storage.py`, `report.py`, `browser.py`

\- \[ ] Viết mới `listing.py` và `detail.py` cho Shopee

\- \[ ] Chạy thử 20 sản phẩm trước, giống lệnh `probe` bên Amazon

\- \[ ] Đối chiếu tay 5 sản phẩm với trang thật trước khi crawl đủ



\---



\## Ba cái bẫy đã gặp ở dự án Amazon, nhớ tránh



1\. Locale sai — Amazon trả giá VND vì nhận ra IP Việt Nam.

&#x20;  Shopee thì ngược lại, nhưng vẫn phải ghi rõ đơn vị tiền trong dữ liệu.



2\. Khối bị ẩn — `inner\_text` chỉ đọc phần hiển thị.

&#x20;  Phần thu gọn phải dùng `text\_content`. Shopee dùng nhiều tab ẩn.



3\. Chưa cuộn đã đọc — nội dung nạp lười, chưa cuộn tới thì chưa tồn tại.

&#x20;  Shopee còn lười hơn Amazon vì là ứng dụng một trang.



\---



\## Khác biệt so với Amazon, cần ghi nhớ khi phân tích



&#x20;Điểm  Amazon  Shopee 

\---------

&#x20;Tín hiệu nhu cầu  BSR + badge tháng  Chỉ đã bán tích luỹ 

&#x20;So sánh giữa sản phẩm  Trực tiếp được  Phải biết tuổi listing mới công bằng 

&#x20;Điểm vào crawl  Node cố định  Từ khoá tìm kiếm, kém ổn định 

&#x20;Biến thể  Mỗi màu một ASIN  Một sản phẩm nhiều phân loại 

&#x20;Dữ liệu người bán  Rất ít  Nhiều tỉ lệ phản hồi, follower 



Hệ quả quan trọng nhất đã bán là tổng tích luỹ từ lúc đăng bán,

không phải theo tháng. Sản phẩm đăng 3 năm bán 10.000 không mạnh hơn

sản phẩm mới bán 2.000. Vì vậy `ngày đăng bán` bên Shopee quan trọng

hơn hẳn bên Amazon. Nếu không lấy được, phải nói rõ giới hạn này

trong mọi kết luận.

