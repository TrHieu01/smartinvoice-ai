# Sửa extraction và vòng đời model — 26/10/2026

Ba lượt ảnh thực gần nhất đều `rules-0.4.1+vlm-fallback`, có 33–93 OCR boxes nhưng 0 sản phẩm. Thời gian tổng từ tạo job đến hoàn tất là 107/152/196 giây; extraction gồm Qwen mất 76–142 giây. Các smoke PNG/JPEG trước đó chỉ kiểm chứng luồng, không chứng minh accuracy bảng hàng.

## Thay đổi

- GPU handler dùng một tiến trình pipeline có thể tái sử dụng: Paddle/Qwen cache giữ trong cùng process giữa các job. Vẫn timeout 240 giây, giết child và khởi động lại khi treo/crash; khóa serialize bảo vệ response của từng job. CPU one-shot giữ nguyên. Active workers=0 vẫn có cold start; cache không tồn tại sau khi RunPod dừng worker.
- Prompt mới chỉ yêu cầu `data`, không bắt model sinh citation cho từng ô. Adapter ghép nguồn từ OCR, kiểm tra schema từng trường và giữ trường/baseline hợp lệ khi một trường sai. Kết quả không đủ nguồn vẫn để trống hoặc giữ baseline, gắn `+qwen3vl4b-partial` và warning. Định dạng có evidence cũ vẫn được kiểm tra nghiêm như trước.
- `rules-0.5.0`: ghép cột theo header/toạ độ, hỗ trợ barcode và đơn giá cùng OCR box, giữ hàng khi thiếu số lượng/đơn giá; bỏ metadata REG khỏi sản phẩm. Đơn vị lấy từ cột có nhãn, không lấy pack size làm ĐVT. Cash tender chỉ dùng làm tổng khi số in trên hóa đơn khớp tổng các dòng đã đọc.

## Kiểm chứng

121 pytest, Ruff và kiểm tra source paths đều qua. Test process thật kiểm chứng hai job dùng chung child, deadline giết child, crash và restart; PDF text chạy hai lần qua IPC. Test adapter kiểm chứng một giá trị sai không làm mất các trường đúng, giữ sản phẩm baseline và từ chối tên không có OCR hỗ trợ.

Replay OCR riêng tư, không chạy model hoặc ghi lại hóa đơn người dùng:

| Mẫu | Số dòng sau sửa | Tổng đọc được |
|---|---:|---:|
| Big C | 12 | 532.024 |
| Lotte | 18 | Chưa xác định |
| Quán ăn | 9 | 537.000 |
| Bách Hóa Xanh | 10 | Chưa xác định |

Đây là các dòng trích xuất, chưa phải số dòng đã xác nhận đúng từng trường. Một số OCR box lỗi vẫn gây thiếu ô/dòng. Không tự cộng dòng để điền tổng khi không có số tổng in trên ảnh. OCR thật chỉ lưu trong `work/` bị gitignore; regression public dùng nội dung giả lập cùng bố cục.

Chưa đo latency/accuracy Qwen trên GPU sau thay đổi. Không chạy thêm hóa đơn RunPod tính phí trong lượt sửa này. Bản sửa không tự xử lý lại hóa đơn đã lưu.
