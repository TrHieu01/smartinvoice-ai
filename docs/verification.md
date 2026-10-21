# Kiểm chứng — 21/10/2026

## Đã qua

- 38 pytest: contract/schema, Auth/error redaction, file validation, PDF pipeline thật, OCR labels/items/currency ambiguity.
- 14 Node/PostgreSQL tests: SQL/RLS, atomic lifecycle, stale version/token, deletion, dispatcher leases/provider ID/retry budget.
- Ruff toàn bộ Python, contract drift, frontend TypeScript và production build Webpack. Turbopack gặp lỗi tiến trình trên Windows hiện tại nên dùng Webpack.
- Supabase Free đã tạo, 4 migration thành công; private bucket và Edge dispatcher đã deploy.
- Live smoke với Supabase thật: 2 user thử, signed upload, validate/hash, worker subprocess, evidence, tenant isolation, signed download, confirm, analytics, delete. Đã dọn toàn bộ dữ liệu giả lập; không dùng RunPod credit.
- PaddleOCR CPU đọc ảnh Việt tổng hợp: tìm được ngày/MST/tiền hàng/thuế/tổng; tên cửa hàng còn sai ký tự. Rules giữ cảnh báo cho nhãn OCR gần đúng. Không coi đây là benchmark.
- Chrome: Auth và Dashboard đã xem; dữ liệu minh họa gắn nhãn rõ, chỉ để xem.

## Chưa kiểm chứng

- Production URL Vercel/Render, Linux Docker build/GHCR worker image.
- RunPod endpoint, cold start, timeout và provider retry thực tế.
- Edge secrets/Vault/Cron chưa bật; chưa coi upload production là sẵn sàng.
- Benchmark hóa đơn thực, concurrency đa kết nối, cảnh báo lỗi tự động, tài khoản demo/video.

## Advisor

Security không có ERROR/WARN. INFO RLS enabled no policy ở jobs/results/outbox là chủ đích deny browser; không thêm policy chỉ để xóa INFO. [Supabase giải thích](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy).

Performance có INFO composite FK/unused indexes trên DB mới. Truy vấn hiện lọc bằng PK/unique hoặc leftmost receipt_id; đo EXPLAIN trên tải thật trước khi thêm index trùng hoặc xóa index chưa dùng. [FK index](https://supabase.com/docs/guides/database/database-linter?lint=0001_unindexed_foreign_keys), [unused index](https://supabase.com/docs/guides/database/database-linter?lint=0005_unused_index).
