# Kiểm chứng — 21/10/2026

## Đã qua

- Trường mới: [CI commit 3e4703d](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39587265399) qua 71 pytest (8 ca ĐVT/địa chỉ/thanh toán, 8 ca adapter VLM), 14 SQL tests và 3 frontend Auth tests; TypeScript/build, Ruff, API Docker và Edge check thành công. API Render công khai version 1.1.0 trước khi áp dụng migration thứ sáu. Đã kiểm tra cột mới, RPC SECURITY INVOKER và deny anon/authenticated execute trên hosted DB; advisor không có ERROR mới.
- Form production đã xem ba trường mới, thêm dòng nháp để kiểm tra input ĐVT rồi bỏ nháp, không lưu thay đổi vào hóa đơn thật. SQL tests xác minh worker complete → human correction → đọc lại ĐVT/địa chỉ/thanh toán và giữ nguyên baseline AI.
- [CPU image build](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39587343837) thành công; endpoint đã lưu digest `sha256:efe3b1883b0f0000313a2389b2e0ffb2f946f94729ffd5f93b0c42168ca6533a`, active=0/max=1/idle=5s. Qwen GPU mới được kiểm thử adapter bằng phản hồi giả lập, chưa benchmark inference thật và chưa thay worker CPU production.

- Parser `rules-0.3.0`: 55 pytest local và [CI commit 80a33b9](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39578596859) thành công (16 ca mới về bố cục), Ruff và contract drift đều qua. Replay OCR thật của hai hóa đơn báo lỗi: 0 → 8 và 0 → 4 sản phẩm, nhận được tổng 187.954 và 105.124; source evidence hợp lệ. Không sửa dữ liệu cũ hoặc tạo job RunPod cho replay. [Chi tiết](extraction.md).
- [Image build 80a33b9](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39578680365) thành công; GHCR public manifest HTTP 200. Endpoint Ready, Release #3 đã nhận digest `sha256:3cd48b86fd2ebaef9657371f9130fc1da4ce233b0f2e4743935826923b132fbb`, active=0/max=1/idle=5s. Chưa chạy lại OCR end-to-end trên cloud bằng phiên bản này; replay chỉ kiểm tra extraction trên OCR cũ.

- 39 pytest trên [CI commit 8c06dd3](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39543587098): contract/schema, Auth/error redaction, file validation, PDF pipeline, OCR labels/items/currency và regression handler trong event loop.
- 14 Node/PostgreSQL tests: SQL/RLS, atomic lifecycle, stale version/token, deletion, dispatcher leases/provider ID/retry budget.
- 3 frontend Auth regression tests phân biệt lỗi giới hạn gửi email/mật khẩu và giữ thông báo an toàn; [CI commit c316cc5](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39573826657) thành công, Vercel Ready.
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
- Brevo Free SMTP đã lưu và kiểm tra lại sau reload Supabase Dashboard; email confirmation vẫn bật. Auth logs ngày 21/10/2026 ghi `/signup` HTTP 200, `/verify` HTTP 303; người dùng xác nhận đã nhận email và đăng nhập được. Đây là kiểm chứng email thật, tách khỏi smoke Admin API. [Chi tiết email](email-delivery.md).

## Chưa kiểm chứng

- Cold start/timeout/provider retry và benchmark hóa đơn thực chưa đo đầy đủ.
- Lần kiểm thử đầu phát hiện adapter gọi asyncio.run trong loop SDK 1.10; đã đổi async handler, regression test và smoke cloud mới thành công. OCR merchant vẫn sai dấu trên fixture; human review đã sửa được.
- Benchmark hóa đơn thực, concurrency đa kết nối, cảnh báo lỗi tự động, tài khoản demo/video.

## Advisor

Advisor sau deployment: không có ERROR. INFO RLS no policy ở jobs/results/outbox là chủ đích deny browser. WARN `pg_net` có extension registration ở public; API/tables của extension nằm trong net, chưa di chuyển vì extension không relocatable. WARN leaked password protection disabled: tính năng này yêu cầu Pro; giữ Free theo yêu cầu. Không tuyên bố advisor sạch WARN. [RLS](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy), [extension schema](https://supabase.com/docs/guides/database/database-linter?lint=0014_extension_in_public), [password protection](https://supabase.com/docs/guides/auth/password-security).

Performance có INFO composite FK/unused indexes trên DB mới. Truy vấn hiện lọc bằng PK/unique hoặc leftmost receipt_id; đo EXPLAIN trên tải thật trước khi thêm index trùng hoặc xóa index chưa dùng. [FK index](https://supabase.com/docs/guides/database/database-linter?lint=0001_unindexed_foreign_keys), [unused index](https://supabase.com/docs/guides/database/database-linter?lint=0005_unused_index).
