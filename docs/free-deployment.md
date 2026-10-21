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

Đã tạo Serverless queue endpoint `smartinvoice-ocr`: CPU 2 vCPU/8 GB, active workers = 0, max workers = 1, idle 5s, execution timeout 300s. Giá UI lúc cấu hình $0.0000306/s. Không tạo Pod hoặc volume. Chủ dự án cho phép tối đa $0.10 credit hiện có cho lần triển khai/kiểm thử này; đây không phải mức trần chi tiêu tích hợp của RunPod.

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

Supabase Cron gọi Edge Function qua pg_net mỗi phút; secret nằm trong Vault. API kích hoạt dispatch ngay khi submit. Dispatcher tự xác thực bằng server-only credential; publishable key không đủ quyền dispatch việc tốn credit. Đã bật lịch trên project SmartInvoice. [Scheduling Edge Functions](https://supabase.com/docs/guides/functions/schedule-functions).

## Giữ trong hạn mức

- Giới hạn app: 5 MB/file, tối đa 5 trang PDF và 20 triệu pixel/ảnh.
- Quota app: 20 uploads/người/ngày, enforcement atomic tại database; tối đa 3 lượt xử lý/hóa đơn.
- Giới hạn tổng storage của app thấp hơn quota provider; cleanup file mồ côi/receipt đã xóa và tránh lưu nhiều bản ảnh render.
- Polling có backoff; giữ raw OCR theo policy retention, không log nội dung hóa đơn.
- Chỉ dùng subdomain có sẵn của provider, không mua domain/add-on.
- Có trạng thái lỗi rõ khi hết quota hoặc credit; không tự nâng gói.

## Tình trạng deployment

Vercel Hobby: [frontend](https://smartinvoice-ai-coral.vercel.app). Render Free: [API health](https://smartinvoice-api-v43w.onrender.com/health). Supabase Free có 5 migration, private Storage, Edge Secrets và Vault/Cron. RunPod CPU đã qua smoke production với ảnh tiếng Việt giả lập; xem [verification](verification.md). Email signup đã dùng Brevo Free SMTP, được người dùng kiểm chứng nhận thư xác nhận và đăng nhập. [Cấu hình email](email-delivery.md), [SMTP](https://supabase.com/docs/guides/auth/auth-smtp).
