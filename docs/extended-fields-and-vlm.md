# Trường bổ sung và thử nghiệm mô hình đọc ảnh

## Các trường mới

| Trường | API | Giới hạn |
|---|---|---|
| Đơn vị tính sản phẩm | `items[].unit` | Text 1–50 ký tự hoặc null |
| Địa chỉ cửa hàng | `merchant_address` | Text 1–500 ký tự hoặc null |
| Phương thức thanh toán | `payment_method` | Text 1–50 ký tự hoặc null |

Các trường đều không bắt buộc. Pydantic nhận được dữ liệu cũ thiếu các trường này và trả null. Worker mới xuất schema 1.1.0; API/database vẫn đọc schema 1.0.0. Không tự sửa kết quả hóa đơn cũ.

Rules hỗ trợ đơn vị trong cột ĐVT hoặc dấu ngoặc cuối tên như `(KG)`, `(HỘP)`. Không suy ra đơn vị bán từ mô tả lốc/hộp hoặc trọng lượng đóng gói. Địa chỉ chỉ lấy từ dòng có nhãn/đường rõ và phần tiếp nối gần nhau; không lấy địa chỉ giao hàng. Thanh toán hỗ trợ tiền mặt/thẻ/chuyển khoản/ví điện tử khi có nhãn rõ; nhiều phương thức khác nhau thì cảnh báo, không chọn bừa.

API, database RPC, lịch sử chỉnh sửa, form và source evidence đều hỗ trợ ba trường. Migration chỉ thêm cột nullable và thay các RPC hiện có, giữ SECURITY INVOKER, ownership checks, RLS và quyền gọi server-only. Triển khai API trước migration, giao diện/worker sau.

## Mô hình GPU chuẩn bị thử

Ứng viên là [Qwen3-VL-4B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct), Apache 2.0, pin revision `ebb281ec70b05090aa6165b016eac8ec08e71b17`. Chưa khẳng định tốt hơn PaddleOCR trên hóa đơn Việt trước khi đo.

- CPU production mặc định `EXTRACTION_BACKEND=rules`; thêm code không tự bật GPU.
- GPU image riêng `worker/Dockerfile.vlm`, workflow thủ công **Build experimental VLM worker image**; PyTorch/Transformers/Accelerate được khóa trong uv.lock.
- Model đọc ảnh và OCR regions, trả JSON gồm data + evidence. Không chạy công cụ hoặc thực thi nội dung hóa đơn.
- Kiểm tra schema, dòng nguồn, đường dẫn field, số tiền/ngày, trùng evidence. Phản hồi không hợp lệ/lỗi GPU trả về rules baseline với cảnh báo; không ghi raw model output hoặc lỗi có nội dung riêng tư vào UI/logs.
- Thiếu năm/ngoại tệ được rules phát hiện không bị model tự điền. Kiểm tra phép tính vẫn chạy; luôn human review.
- Giới hạn 5 trang theo app; prompt tối đa 100 OCR regions, context 14.000 tokens, output 4.096 tokens, generation 150s, subprocess 240s. Tài liệu dài/phức tạp có thể fallback; không coi JSON hợp lệ là bảo đảm dữ liệu đúng.

## Đề xuất lượt thử cần chốt ngân sách

Chưa tạo endpoint GPU hoặc gọi inference tính phí khi chưa được người dùng duyệt ngân sách riêng.

Đề xuất endpoint thử `smartinvoice-vlm`, GPU 24 GB (ưu tiên L4/A5000/3090), active=0, max=1, idle=5s, execution=300s, container disk 40 GB, không network volume. Giữ endpoint CPU hiện có làm đường lui. API key mới chỉ GET/POST endpoint thử, chỉ lưu phía server.

Đề xuất tối đa **0,50 USD từ credit hiện có** cho tối đa 3 hóa đơn thử; không nạp tiền/nâng gói và không chuyển traffic production sang GPU tự động. Ngân sách chỉ có hiệu lực sau khi người dùng đồng ý. Giá công khai ngày 21/10/2026 cho nhóm Serverless 24 GB là khoảng $0,69/giờ GPU; chi phí còn phụ thuộc initialization, thời gian chạy, idle và disk. [Giá RunPod](https://www.runpod.io/pricing), [cách tính khi job lỗi](https://www.runpod.io/blog/failed-requests-real-charges-how-runpod-serverless-billing-works-when-workers-fail).

Đây là giới hạn chi tiêu do phiên thử theo dõi, không phải hard cap tự động của RunPod. Không gửi thêm job nếu chi phí không còn đủ; kết thúc lượt thử phải dừng GPU rồi xác nhận worker đã ngừng. Đo đúng theo từng trường/sản phẩm, thời gian và chi phí, đối chiếu baseline trước khi quyết định dùng lâu dài.

## Image thử đã build

[Build 75ab41d](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39588380711) thành công; package public và anonymous manifest HTTP 200. Image pin:

```text
ghcr.io/trhieu01/smartinvoice-ai-worker-vlm@sha256:7259fbf7326319360cb6cc19810e5b00b7e1ce2f55c9579f20f15eb92a40a581
```

Weights và processor được nạp sẵn; CPU build đã kiểm tra processor nhận ảnh giả lập. Đây chưa phải kiểm chứng inference hay chất lượng trích xuất GPU. Candidate dùng baseline rules-0.4.0; production CPU dùng rules-0.4.1 với guard địa chỉ người nhận bổ sung. Adapter VLM không thay đổi giữa hai bản.
