# Trích xuất theo bố cục — rules-0.3.0

Worker giữ PaddleOCR Latin/CPU và PDF text fast path; không thêm LLM, GPU hoặc dịch vụ trả phí. API/schema giữ nguyên.

## Thay đổi

- Bảng hóa đơn: ghép tên ở dòng trên với dòng số lượng, đơn giá, thành tiền phía dưới khi có tiêu đề cột; không ghép khác trang hoặc cách xa nhau.
- Thẻ sản phẩm trong ảnh đơn hàng: dùng nhãn SL/Qty và tọa độ để ghép tên nhiều dòng, giá và số lượng; loại chữ trong ảnh thumbnail. Giữ sản phẩm giá 0, không lấy giá cũ phía dưới làm đơn giá.
- Số chứng từ: hỗ trợ Số CT, S CT, Số chứng từ và Đơn hàng #.
- Tổng tiền: hỗ trợ giá ở dòng kế tiếp gần nhãn; chấp nhận nhãn OCR thiếu ít ký tự như “Tng tien”, “Tng tin” và luôn cảnh báo để đối chiếu. Không lấy số tiền lớn nhất hoặc tự cộng sản phẩm thay tổng thanh toán.
- Tên cửa hàng: bỏ giờ/pin, menu, tìm kiếm và tiêu đề hóa đơn; dừng trước phần thông tin đơn hàng. Không có nguồn rõ thì trả null.
- Ngày thiếu năm: giữ null và cảnh báo, không tự lấy năm hiện tại.
- Mỗi trường có source evidence; giá trị mâu thuẫn/không khớp phép tính vẫn được cảnh báo, không tự sửa.

## Kiểm chứng

16 regression tests trong `backend/tests/test_receipt_layout.py`, gồm bố cục nhiều dòng/thẻ sản phẩm, khuyến mãi giá 0, giá mâu thuẫn, giới hạn trang/khoảng cách, ngày thiếu năm, nhãn và evidence. Kiểm thử schema xác minh mọi trường đã điền tham chiếu dòng OCR hợp lệ.

Replay OCR đã lưu của hai hóa đơn người dùng báo lỗi, không gọi RunPod và không sửa hóa đơn trong database:

| Mẫu | Sản phẩm trước → sau | Tổng tiền trước → sau |
|---|---|---|
| Hóa đơn giấy | 0 → 8 | null → 187.954 |
| Ảnh đơn hàng | 0 → 4 | null → 105.124 |

Đây là kiểm tra hồi quy hai trường hợp, không phải benchmark accuracy. OCR tên cửa hàng/sản phẩm vẫn có thể sai dấu. Ảnh đơn hàng thiếu tên cửa hàng và năm nên vẫn cần bổ sung. Không commit ảnh, OCR riêng tư hoặc địa chỉ người dùng vào repository.

## Sử dụng bản cập nhật

Ngày 21/10/2026: endpoint `smartinvoice-ocr` báo Ready, Release #3 dùng image từ commit `80a33b9`. [CI](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39578596859) và [image build](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39578680365) thành công. Giữ active=0, max=1, idle=5s; không đổi CPU sang GPU. Chưa chạy job OCR cloud mới trong lần cập nhật này.

Chỉ worker dùng image mới mới áp dụng rules-0.3.0. Kết quả đã lưu không tự thay đổi và không ghi đè chỉnh sửa của người dùng. Sau khi cập nhật endpoint, tải file lên thành hóa đơn mới để so sánh; giữ bản cũ khi cần đối chiếu.

Ảnh quá mờ, bố cục lạ hoặc hai giá không phân biệt được vẫn cần human review. Bước tiếp theo là tập test độc lập và đo extraction theo từng trường trước khi quyết định bổ sung VLM fallback.
