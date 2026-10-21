# Nền tảng miễn phí và RunPod

Đã tra cứu tài liệu chính thức ngày 21/10/2026. Chủ dự án có tài khoản/credit RunPod, chưa tạo máy. Chọn gói Free cho nền tảng web; compute RunPod được hạch toán riêng. Không dùng trial hết hạn rồi tự chuyển sang paid.

## Phương án được chọn

| Thành phần | Nền tảng | Giới hạn / quyết định |
| --- | --- | --- |
| Next.js | Vercel Hobby | Dùng cho portfolio cá nhân, phi thương mại |
| FastAPI | Render Free | Container API nhẹ; không chạy OCR trên Render |
| PostgreSQL + Auth + Storage | Supabase Free | Private bucket và RLS; không nâng organization lên paid |
| Dispatch/reconciliation | Supabase Cron + Edge Function | Chỉ gửi job/cleanup; không chạy model trong Edge Function |
| OCR | RunPod Serverless Flex | Dùng credit hiện có; 0 active, tối đa 1 worker; tính phí compute |
| CI | GitHub Actions standard runner | Public repository, hoặc hạn mức Free nếu private |
| Logs/metrics | Logs nền tảng + database jobs | Không phụ thuộc Sentry/monitoring paid |

Vercel Hobby dành cho dự án cá nhân phi thương mại. Không chọn Pro trial. [Vercel Hobby](https://vercel.com/docs/plans/hobby).

Render Free ngủ sau 15 phút không có request và có cold start. Dùng một API service, không chọn Render Postgres Free cho dữ liệu lâu dài vì database này hết hạn sau 30 ngày. Nếu có payment method, bandwidth/build vượt quota có thể tính phí; cấu hình dự án không gắn payment method để dịch vụ dừng khi hết quota. [Render Free](https://render.com/docs/free), [Render billing FAQ](https://render.com/docs/faq).

Supabase Free hiện có 500 MB database và 1 GB file storage; project có thể tạm dừng khi không hoạt động. Free không thu phí vượt mức, nhưng có thể hạn chế dịch vụ. [Pricing](https://supabase.com/pricing), [Cost control](https://supabase.com/docs/guides/platform/cost-control).

## RunPod: sử dụng credit, không gọi là miễn phí

Chưa tạo endpoint, Pod, network volume hoặc gọi inference. Đề xuất Serverless queue endpoint: active workers = 0, max workers = 1, một job mỗi worker, timeout hữu hạn. Dùng Flex thay vì bật worker luôn chạy. Khi deploy sẽ xác minh chính xác các field cấu hình theo SDK/API đang dùng.

Compute có thể tính phí trong thời gian khởi động model, xử lý và idle timeout. Credit là nguồn thanh toán, không biến dịch vụ thành free tier. Không tự nạp tiền, bật auto-top-up hoặc mua volume. [RunPod pricing](https://docs.runpod.io/serverless/pricing).

Container OCR preload model phù hợp; cần benchmark CPU/GPU để chọn loại máy. Chưa chốt GPU dựa trên giả định accuracy/latency. Không dùng RunPod như tiến trình polling database chạy vô hạn trong mô hình Serverless: dispatcher gửi từng job, handler xử lý rồi trả kết quả.

## Các nền tảng thay thế đã xem

| Nền tảng | Có phù hợp không? |
| --- | --- |
| Cloudflare Pages Free | Phương án thay frontend nếu dùng static export; Next.js SSR cần adapter/runtime riêng |
| Cloudflare Workers Free | Phù hợp HTTP orchestration nhỏ; không dùng để chạy PaddleOCR |
| Hugging Face Docker Spaces | Không chọn cho yêu cầu free tuyệt đối: tài liệu hiện tại yêu cầu paid plan để tạo compute Space |
| GitHub Actions | Dùng CI/test, không dùng như server OCR hoạt động liên tục |

Cloudflare Pages miễn phí static requests; Workers Free có giới hạn CPU và memory nhỏ. [Pages](https://developers.cloudflare.com/pages/functions/pricing/), [Workers limits](https://developers.cloudflare.com/workers/platform/limits/).

Hugging Face phân biệt CPU Basic không có phí theo giờ với điều kiện tạo Space: Docker/Gradio compute yêu cầu gói paid, có ngoại lệ ZeroGPU cho một số tài khoản Free. Không coi ngoại lệ là hạ tầng Docker/PaddleOCR bảo đảm miễn phí. [Spaces overview](https://huggingface.co/docs/hub/spaces-overview).

GitHub Actions standard runners miễn phí cho public repository; larger runners và storage vượt mức có quy tắc tính phí riêng. [GitHub billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

## Queue và cleanup không cần Google Cloud

Supabase Cron có thể gọi Edge Function qua pg_net; secret nằm trong Vault. Lịch reconcile dự kiến 5 phút, API kích hoạt dispatch ngay khi submit. Dispatcher phải tự xác thực bằng server-only credential; publishable key không phải bằng chứng đủ quyền để dispatch việc tốn credit. Chưa bật lịch trên tài khoản thật. [Scheduling Edge Functions](https://supabase.com/docs/guides/functions/schedule-functions).

## Giữ trong hạn mức

- Giới hạn app: 5 MB/file, tối đa 5 trang PDF và 20 triệu pixel/ảnh.
- Dự kiến quota app cho demo: 20 uploads/người/ngày; cần enforcement atomic ở backend trước public demo.
- Giới hạn tổng storage của app thấp hơn quota provider; cleanup file mồ côi/receipt đã xóa và tránh lưu nhiều bản ảnh render.
- Polling có backoff; giữ raw OCR theo policy retention, không log nội dung hóa đơn.
- Chỉ dùng subdomain có sẵn của provider, không mua domain/add-on.
- Có trạng thái lỗi rõ khi hết quota hoặc credit; không tự nâng gói.

## Tình trạng deployment

Chưa đăng nhập hay thay đổi tài khoản Vercel/Render/Supabase/RunPod. Chưa có URL demo. Bảng trên là lựa chọn kiến trúc đã nghiên cứu, không phải xác nhận các dịch vụ đã được tạo hoặc triển khai thành công.
