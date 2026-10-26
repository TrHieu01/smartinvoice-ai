# Deployment

Supabase Free hiện tại: `smartinvoice-ai`, ref `rnjamfgzckmgvvpuywgh`, `TrHieu01's Org`, Singapore. Không cần máy cá nhân duy trì OCR khi cloud deployment hoàn tất.

## Supabase

6 migration đã áp dụng lên project mới; không chạy lại vào database đã có schema. Bucket `receipts` private. Edge `dispatch-jobs` đã deploy; dùng `x-dispatch-secret` tự xác thực, không mở truy cập khi thiếu secret. JWT gateway tắt để Cron/API gọi bằng shared secret. Migration `receipt_optional_fields` thêm ĐVT, địa chỉ, phương thức thanh toán và cho phép extraction schema 1.1.0 cùng bản 1.0.0.

Edge Secrets đang dùng: `DISPATCHER_SECRET`, `RUNPOD_ENDPOINT_ID=dvaal7yuostlnu`, `RUNPOD_VLM_TRIAL_API_KEY`. Tên key giữ từ phiên thử; credential hiện chỉ cho phép GET/POST endpoint Qwen này, không có quyền GraphQL. Dispatcher v5 không fallback sang key CPU. `SUPABASE_URL` và `SUPABASE_SERVICE_ROLE_KEY` được nền tảng inject. Dispatcher secret khớp backend và Vault.

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

Production từ 26/10/2026 dùng endpoint `smartinvoice-vlm` (`dvaal7yuostlnu`), Qwen3-VL-4B trên GPU 24 GB. Chạy Actions **Build experimental VLM worker image**, đợi build/push GHCR thành công rồi pin digest. `runtime_only=true` chỉ dùng khi dependencies không đổi, tái sử dụng các lớp model đã xác minh. Package public không cần registry credential; không nhúng token vào image.

Endpoint CPU `smartinvoice-ocr` (`ouae2lld2k5far`) đã đặt active=0/max=0. PaddleOCR/PDF preprocessing trong image GPU vẫn dùng CPU; Qwen inference dùng CUDA. Khi Qwen thất bại, rules fallback chạy trong cùng worker GPU và ghi rõ `+vlm-fallback`, không gửi việc sang endpoint CPU.

Server key nằm trong RunPod Secrets, env tham chiếu `{{ RUNPOD_SECRET_SMARTINVOICE_SUPABASE_KEY }}`. Start command: `python -u -m worker.handler`; không dùng benchmark handler cho production. Env: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `EXTRACTION_BACKEND=qwen_vl`. [Các trường mới và kiểm thử GPU](extended-fields-and-vlm.md).

Image hiện hành từ commit `46dcf57`, [build thành công](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/40264352426), anonymous GHCR manifest HTTP 200:

```text
ghcr.io/trhieu01/smartinvoice-ai-worker-vlm@sha256:3d7e699f5bd090387e842a6f96eb551993adf892432e4599a1d639c92d2b8571
```

GPU Flex, active/min 0, max 1, concurrency 1, idle 5s, execution timeout 300s, disk 40 GB. Không tạo Pod chạy liên tục/network volume. Giá nhóm GPU 24 GB hiển thị lúc cấu hình khoảng $0,69/giờ; compute vẫn trừ credit khi chạy. Ngân sách phiên chuyển đổi tối đa $1 là giới hạn theo dõi, không phải hard cap RunPod.

Image Qwen lớn; lần worker tải/giải nén image mới có thể mất vài phút trước khi bắt đầu xử lý. Phiên 26/10 ghi nhận queue delay khoảng 3m43s trên lần PDF thứ hai. Không coi queue delay này là inference latency; chưa có benchmark P95. Giữ 0 worker thường trực đồng nghĩa chấp nhận cold start.

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
