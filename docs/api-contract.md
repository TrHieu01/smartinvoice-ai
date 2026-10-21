# REST API Contract v1.0.0

Nguồn máy đọc: `contracts/openapi.json`, được sinh từ `backend/app/schemas/contracts.py` và `scripts/export_contracts.py`. Đây là contract; chưa có server API runtime.

## Quy ước chung

- Base path `/api/v1`; JSON UTF-8, snake_case. Timestamps RFC3339 có timezone; dates YYYY-MM-DD.
- Mọi route receipt/analytics yêu cầu Supabase access token. Backend xác minh chữ ký, issuer, audience, expiry, subject và loại user phù hợp. Không tin `getSession()` phía browser để authorization server.
- Đăng ký/đăng nhập/logout do Supabase Auth; không tạo API password riêng ở FastAPI.
- Tiền là chuỗi thập phân (`"108000.00"`); frontend không dùng float để tổng hợp số liệu chính thức.
- Một HTTP 202 chỉ xác nhận công việc đã lưu bền vững; không có nghĩa OCR đã chạy.
- Tất cả endpoint nhận receipt ID: xác minh ownership trước khi đọc, ký URL, sửa, retry hoặc xóa. ID người khác và ID không tồn tại đều trả 404.
- Trả `Cache-Control: no-store` cho dữ liệu người dùng và signed URLs; không cache dữ liệu riêng tư trên CDN.
- `X-Request-ID` UUID do API tạo; error response chứa cùng ID. Không trả raw exception, query SQL hoặc provider response.

## Endpoints

| Method | Endpoint | Kết quả |
| --- | --- | --- |
| POST | `/receipts` | 201 tạo row và upload ticket; 200 replay cùng key |
| POST | `/receipts/{id}/submit` | 202, verify file thật rồi tạo durable job |
| POST | `/receipts/{id}/retry` | 202, run mới cho receipt failed |
| GET | `/receipts/{id}` | 200, dữ liệu hiện tại + latest AI result gốc |
| GET | `/receipts/{id}/status` | 200, trạng thái/job/error_code/poll_after_ms |
| GET | `/receipts/{id}/file` | 200, signed preview URL TTL 300 giây |
| PATCH | `/receipts/{id}` | 200, lưu full editable snapshot hoặc xác nhận |
| GET | `/receipts` | 200, search/filter/pagination |
| DELETE | `/receipts/{id}` | 202, tombstone và cleanup event |
| GET | `/analytics/summary` | 200, tổng hợp confirmed VND receipts |
| GET | `/health` ngoài base path | 200, liveness, không yêu cầu token |

Không public endpoint worker/RunPod API key. Dispatcher và worker dùng server credentials riêng.

## Create / upload

`Idempotency-Key` là UUID bắt buộc khi create/submit/retry. Body create:

```json
{"filename":"receipt.png","content_type":"image/png","size_bytes":120000}
```

Chỉ nhận 4 MIME trong schema và byte count 1..5.000.000. API lưu hash canonical request payload. Cùng user/key/body trả cùng receipt; khác body trả 409 `idempotency_conflict`. Replay khi vẫn awaiting_upload có thể trả ticket mới, phải gia hạn `upload_expires_at` an toàn trước khi trả response. Nếu đã submit, `upload=null`, không phát ticket mới.

Ticket có `bucket`, `path`, `token`, `expires_at`, `upsert=false`, `max_bytes`. Frontend dùng Supabase SDK `uploadToSignedUrl(path, token, file)`; không tự tạo PUT request theo giả định giao thức. Expiry upload 2 giờ, khác expiry preview 300 giây.

## Submit / retry

Submit body rỗng. Backend tải object theo path trong DB và kiểm chứng bytes/size/MIME/pages/pixels. Không nhận URL, storage_path hoặc user_id trong request. Chưa upload trả 409 `upload_missing`; file không hợp lệ trả 422, quá lớn 413, MIME không hỗ trợ 415.

Lock receipt trước tạo job. Submit lặp lại trả job đã có, không chạy OCR lần hai. Retry chỉ cho trạng thái failed, tạo run_number tăng 1; cùng request key trả lại run đó. Một receipt không có hai job active.

Queue lưu database, dispatcher gọi RunPod sau transaction. Không chờ OCR trong request HTTP. `poll_after_ms` gợi ý 2000..30000 ms khi pending/running, null khi terminal. Frontend tăng backoff và dừng polling dày sau 2 phút, không tự chuyển receipt sang failed.

## Human review

Ví dụ đầy đủ: `contracts/examples/review.json`.

PATCH dùng `expected_version`, `action=save|confirm`, `data` chứa **toàn bộ** editable data và `category`. Đây là full replacement của các trường cho phép sửa; không phải JSON Merge Patch. Không nhận `status`, owner, AI JSON, storage path hay version mới do client tự đặt.

Chỉ sửa receipt needs_review/confirmed. Save chuyển về needs_review; confirm yêu cầu merchant, purchase_date, total_amount, currency. Ngày sai hoặc tiền sai kiểu trả 422. Arithmetic mismatch tạo warning và giữ số do người dùng xác nhận, không tự tính lại thay dữ liệu nguồn.

Transaction so sánh version, lưu before/after snapshots và changed_fields, thay items, cập nhật receipt/version; tất cả thành công hoặc rollback. Nếu version cũ trả 409 `version_conflict`; frontend tải lại trước khi merge thay đổi. Các repeat PATCH dùng cùng version không áp dụng hai lần.

AI result gốc không bị sửa. Warnings hiện tại được validate lại và nằm ở `ReceiptDetail.warnings`; `latest_extraction.warnings` giữ nguyên theo lần AI chạy.

## List / analytics

List có page>=1, page_size 1..100, merchant substring, status, date_from/to, min/max_amount và sort cố định. Default `created_at_desc`; luôn thêm ID làm tie-breaker, NULLS LAST cho ngày/số tiền. Filter ngày và tiền bao gồm hai đầu; khoảng đảo ngược trả 422. Search escaping `%`/`_`, dùng query parameters thay SQL nối chuỗi.

Analytics yêu cầu date_from/date_to, inclusive, tối đa 366 ngày theo purchase_date. Chỉ tính confirmed và VND; tháng không có chi tiêu vẫn có bucket 0. Count và total cùng filter. Không tự đổi tỷ giá, không tự dùng ngày upload cho purchase_date bị thiếu.

## Error envelope

```json
{
  "error": {
    "code": "version_conflict",
    "message": "Hóa đơn đã được cập nhật. Vui lòng tải lại.",
    "request_id": "33333333-3333-4333-8333-333333333333",
    "details": []
  }
}
```

| HTTP | Codes tiêu biểu |
| --- | --- |
| 401 | authentication_required, invalid_token |
| 404 | receipt_not_found |
| 409 | invalid_state, version_conflict, idempotency_conflict, upload_missing |
| 413 | file_too_large |
| 415 | unsupported_media_type |
| 422 | invalid_request, corrupt_file, encrypted_pdf, page_limit_exceeded, image_too_large |
| 429 | quota_exceeded, rate_limited; kèm Retry-After |
| 503 | dependency_unavailable; không thay đổi thành công OCR giả |

App phải override FastAPI validation exception handler để lỗi 422 theo envelope chung. Lỗi xử lý đã enqueue nằm trong JobSummary.error_code (ví dụ ocr_timeout, ocr_failed, provider_unavailable); không lộ stack trace.

## Xóa

DELETE lần đầu và lặp lại khi tombstone còn tồn tại đều 202. Sau hard-delete trả 404. GET/list/analytics không trả receipt deleting. Physical cleanup chỉ hoàn tất sau expiry các upload ticket, xóa Storage thành công và xóa các row con. Không báo file đã bị xóa vật lý ngay khi API mới trả 202.
