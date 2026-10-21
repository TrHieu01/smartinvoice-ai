# Kiểm chứng — 21/10/2026

## Đã qua

- 39 pytest trên [CI commit 8c06dd3](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39543587098): contract/schema, Auth/error redaction, file validation, PDF pipeline, OCR labels/items/currency và regression handler trong event loop.
- 14 Node/PostgreSQL tests: SQL/RLS, atomic lifecycle, stale version/token, deletion, dispatcher leases/provider ID/retry budget.
- Ruff toàn bộ Python, contract drift, frontend TypeScript và production build Webpack. Turbopack gặp lỗi tiến trình trên Windows hiện tại nên dùng Webpack.
- Supabase Free đã tạo, 5 migration thành công; private bucket và Edge dispatcher đã deploy. Edge Secrets và Vault/Cron mỗi phút đã cấu hình; đã ghi nhận Cron HTTP 200.
- Live smoke với Supabase thật: 2 user thử, signed upload, validate/hash, worker subprocess, evidence, tenant isolation, signed download, confirm, analytics, delete. Đã dọn toàn bộ dữ liệu giả lập; không dùng RunPod credit.
- PaddleOCR CPU đọc ảnh Việt tổng hợp: tìm được ngày/MST/tiền hàng/thuế/tổng; tên cửa hàng còn sai ký tự. Rules giữ cảnh báo cho nhãn OCR gần đúng. Không coi đây là benchmark.
- [Frontend Vercel](https://smartinvoice-ai-coral.vercel.app) Ready, [Render API](https://smartinvoice-api-v43w.onrender.com/health) HTTP 200 version 0.2.0. API production đã qua smoke hai user/PDF: CORS allow/deny, Auth, upload/validate, worker cục bộ, phân quyền, review, analytics, delete; dữ liệu thử đã dọn.
- Linux API Docker build và [CI ban đầu](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39540302643) xanh. [Worker image build](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39540805798) thành công; GHCR public và anonymous manifest HTTP 200.
- [Worker build mới](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39543659207) đã sửa async handler; endpoint pin digest `sha256:28256a60e559909bda7e9883b5065fbae2c9d0dc25e0b95b3535bbf3f159cd88`.
- Smoke cloud với ảnh tiếng Việt giả lập **passed**: API Render → private signed upload → Edge/Cron → RunPod → evidence → hai tenant → signed download → confirm → analytics 110.000 VND → delete. Hai user, file và DB test đã dọn. Đây là một fixture, không phải accuracy benchmark.
- Chrome production: Auth và Dashboard mẫu đã xem; dữ liệu minh họa gắn nhãn rõ, chỉ để xem.
- Chrome production với tài khoản thử: đăng nhập, tải lại lịch sử, xem ảnh gốc cạnh OCR/evidence, sửa tên cửa hàng sai dấu, chọn Ăn uống, xác nhận và kiểm tra dashboard 110.000 VND. Ảnh được nạp qua API vì tiện ích Chrome chưa cho phép chọn file cục bộ; thao tác chọn/upload file qua browser automation chưa kiểm chứng. Dữ liệu/tài khoản thử đã dọn.

## Chưa kiểm chứng

- Cold start/timeout/provider retry và benchmark hóa đơn thực chưa đo đầy đủ.
- Lần kiểm thử đầu phát hiện adapter gọi asyncio.run trong loop SDK 1.10; đã đổi async handler, regression test và smoke cloud mới thành công. OCR merchant vẫn sai dấu trên fixture; human review đã sửa được.
- Đăng ký email public chưa sẵn sàng: cần custom SMTP; email xác nhận vẫn bật. Test user dùng Admin API, không chứng minh gửi email.
- Benchmark hóa đơn thực, concurrency đa kết nối, cảnh báo lỗi tự động, tài khoản demo/video.

## Advisor

Advisor sau deployment: không có ERROR. INFO RLS no policy ở jobs/results/outbox là chủ đích deny browser. WARN `pg_net` có extension registration ở public; API/tables của extension nằm trong net, chưa di chuyển vì extension không relocatable. WARN leaked password protection disabled: tính năng này yêu cầu Pro; giữ Free theo yêu cầu. Không tuyên bố advisor sạch WARN. [RLS](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy), [extension schema](https://supabase.com/docs/guides/database/database-linter?lint=0014_extension_in_public), [password protection](https://supabase.com/docs/guides/auth/password-security).

Performance có INFO composite FK/unused indexes trên DB mới. Truy vấn hiện lọc bằng PK/unique hoặc leftmost receipt_id; đo EXPLAIN trên tải thật trước khi thêm index trùng hoặc xóa index chưa dùng. [FK index](https://supabase.com/docs/guides/database/database-linter?lint=0001_unindexed_foreign_keys), [unused index](https://supabase.com/docs/guides/database/database-linter?lint=0005_unused_index).
