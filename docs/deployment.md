# Deployment

Supabase Free hiện tại: `smartinvoice-ai`, ref `rnjamfgzckmgvvpuywgh`, `TrHieu01's Org`, Singapore. Không cần máy cá nhân duy trì OCR khi cloud deployment hoàn tất.

## Supabase

5 migration đã áp dụng lên project mới; không chạy lại vào database đã có schema. Bucket `receipts` private. Edge `dispatch-jobs` đã deploy; dùng `x-dispatch-secret` tự xác thực, không mở truy cập khi thiếu secret. JWT gateway tắt để Cron/API gọi bằng shared secret.

Edge Secrets đã cấu hình: `DISPATCHER_SECRET`, `RUNPOD_ENDPOINT_ID`, `RUNPOD_API_KEY`. `SUPABASE_URL` và `SUPABASE_SERVICE_ROLE_KEY` được nền tảng inject. Dispatcher secret khớp backend và Vault. API key RunPod bị giới hạn GET/POST tới endpoint SmartInvoice, không có quyền GraphQL.

Vault có hai secret: `smartinvoice_dispatch_url` và `smartinvoice_dispatch_secret`. Migration thứ năm bật pg_cron/pg_net; đã chạy `supabase/setup-dispatch-cron.sql` một lần, lịch `smartinvoice-dispatch` mỗi phút. Script chặn cài trùng; cài mới cần điền Vault trước khi bật lịch.

Auth Site URL và Redirect URL hiện là `https://smartinvoice-ai-coral.vercel.app`. Giữ xác nhận email. Custom SMTP đã cấu hình bằng **Brevo Free**, host `smtp-relay.brevo.com`, port `465` (SSL); credential chỉ lưu trong Supabase Auth settings. Người dùng đã nhận thư xác nhận và đăng nhập thành công. [Cấu hình và kiểm chứng email](email-delivery.md), [tài liệu SMTP](https://supabase.com/docs/guides/auth/auth-smtp).

## Render Free

Import repo, tạo Blueprint từ `render.yaml`. Bắt buộc `plan: free`, region Singapore, Docker context root, Dockerfile `backend/Dockerfile`, health `/health`. Không tạo database/disk trả phí.

Điền `SUPABASE_SECRET_KEY`, `CORS_ORIGINS` (URL Vercel chính xác), `DISPATCHER_SECRET`. Auto deploy `checksPass` chờ CI. `/ready` chỉ kiểm tra cấu hình, smoke mới xác minh upstream. Không thêm phương thức thanh toán nếu muốn dừng khi hết quota thay vì phát sinh phí. Free API có thể ngủ.

## Vercel Hobby

Import repo, **Root Directory = frontend**, framework Next.js. Install/build có trong `frontend/vercel.json`. Điền ba biến public:

```text
NEXT_PUBLIC_SUPABASE_URL=https://rnjamfgzckmgvvpuywgh.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<publishable key>
NEXT_PUBLIC_API_BASE_URL=https://<api-name>.onrender.com
```

Env được nhúng khi build; thay đổi cần redeploy. Không đưa secret/service-role key vào frontend. Git integration tự deploy khi push; chỉ chia sẻ URL demo sau khi kiểm tra cả API và worker.

## RunPod

Chạy Actions **Build worker image**, đợi build/push GHCR thành công. Package private cần đúng registry credential; không nhúng token vào image. Pin image bằng SHA đã kiểm tra.

Image hiện dùng `paddlepaddle` CPU + mobile detector/Latin recognizer, tải model lúc build. Không đặt `OCR_DEVICE=gpu:0` với wheel CPU. Endpoint `smartinvoice-ocr` (`ouae2lld2k5far`) dùng CPU 2 vCPU/8 GB, giá UI lúc cấu hình $0.0000306/s. Đã xác minh có CPU Serverless trong tài khoản.

Image public đã build và cập nhật endpoint: `ghcr.io/trhieu01/smartinvoice-ai-worker@sha256:3cd48b86fd2ebaef9657371f9130fc1da4ce233b0f2e4743935826923b132fbb` (commit `80a33b9`, async handler và parser `rules-0.3.0`). Server key nằm trong RunPod Secrets, env tham chiếu `{{ RUNPOD_SECRET_SMARTINVOICE_SUPABASE_KEY }}`. [Kiểm chứng extraction và cách thử bản mới](extraction.md).

Flex, active/min 0, max 1, concurrency 1, idle timeout ngắn, execution timeout 300s, TTL 600s. Không tạo Pod chạy liên tục/network volume. Env: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `OCR_DEVICE=cpu` cho image hiện tại. Compute vẫn trừ credit khi chạy.

Input: `{"input":{"job_id":"<UUID job đã submit>"}}`. Không gửi ảnh/URL/credential trong input. Chỉ coi thành công khi receipt trong DB chuyển `needs_review`.

## Smoke production

1. Đăng ký/xác nhận email/đăng nhập; tài khoản khác không xem được dữ liệu.
2. Upload ảnh Việt/Anh, PDF text/scan ≤5 trang; thử file quá lớn/MIME sai.
3. Theo dõi queued → processing → needs_review, kiểm tra source evidence.
4. Sửa/xác nhận, kiểm tra dashboard và AI baseline bất biến.
5. Thử retry, version conflict, duplicate submit; không sinh job song song.
6. Xóa, kiểm tra ẩn ngay và dọn file sau deadline.
7. Kiểm tra logs, quota, RunPod credit. Không dùng keep-alive để né sleep Free.

Nguồn: [Render Blueprint](https://render.com/docs/blueprint-spec), [Vercel Git](https://vercel.com/docs/git), [PaddleOCR multilingual](https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html), [RunPod handlers](https://docs.runpod.io/serverless/workers/handler-functions).
