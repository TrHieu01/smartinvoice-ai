# Các mốc triển khai SmartInvoice AI

Trạng thái runtime/triển khai mới nhất: xem [verification.md](verification.md). Checklist dưới đây được lập ở mốc thiết kế; các phần đang còn cần bổ sung được tách rõ.

## Mốc 1 - Contracts

- [x] Database schema, constraints, RLS và private bucket migration.
- [x] Public OpenAPI và JSON Schema AI/job payload.
- [x] Pydantic source, ví dụ và drift check.
- [x] Test SQL thực trên PostgreSQL/WASM và test schema/OpenAPI.
- [x] Nghiên cứu nền tảng Free, tách riêng compute RunPod credit.
- [x] GitHub Actions CI chạy thành công trên repository public.

## Mốc 2 - Backend và Supabase integration

- [x] FastAPI cấu hình, Auth token verification, CORS allowlist và lỗi thống nhất.
- [x] Atomic server-only RPC: create/submit/retry/claim/complete/review/delete; tenant checks.
- [x] Signed upload, kiểm chứng object và quota app.
- [x] API smoke với 2 người dùng, unauthorized ID; SQL test stale version.
- [ ] Benchmark concurrency nhiều connection trên hosted Postgres.
- [x] Supabase Free thật để test Auth/Storage HTTP và advisors.

## Mốc 3 - AI worker và RunPod adapter

- [x] PDF text extraction + fallback OCR, kiểm tra trang/pixel/định dạng.
- [x] PaddleOCR vi/en + OpenCV, rules và validation bằng Decimal.
- [x] Handler nhận job_id, lease/fencing và commit nguyên tử.
- [x] Container Linux/GHCR với dependency/model version pin rõ.
- [ ] Benchmark CPU/GPU trên tập hóa đơn độc lập.
- [x] Supabase Edge dispatcher + lease, provider request ID, bounded retries.
- [x] Cron reconciliation/cleanup mỗi phút; secret trong Vault, API key chỉ cho endpoint SmartInvoice.
- [x] RunPod CPU Serverless: active=0, max=1, idle 5s, execution timeout 300s.

## Mốc 4 - Frontend

- [x] Next.js/TypeScript/Tailwind, component HTML native/lucide.
- [ ] Type frontend sinh từ OpenAPI; shadcn/ui là tùy chọn, chưa tích hợp.
- [x] Auth, Dashboard, Upload, Review và History.
- [x] Review cạnh ảnh/PDF, evidence highlight, source/original AI và editable data tách rõ.
- [x] Polling backoff 2–30s, giới hạn 15 phút, lỗi request và version conflict.
- [ ] Responsive/accessibility; test upload -> process -> review -> analytics.

## Mốc 5 - Demo và portfolio

- [x] Repository public, CI và worker image build đã chạy thành công.
- [x] Build/test containers và frontend; deploy Vercel Hobby + Render Free + Supabase Free.
- [x] RunPod CPU endpoint pin digest đã kiểm tra, trong giới hạn credit $0.10 được cấp phép.
- [x] Smoke production bằng ảnh tiếng Việt: upload → Edge → RunPod → review → analytics, tenant isolation và cleanup.
- [x] Brevo Free SMTP cho đăng ký public; người dùng đã nhận email xác nhận và đăng nhập thành công.
- [ ] Smoke tests, monitoring, lỗi mẫu và kiểm tra không log dữ liệu hóa đơn.
- [ ] Tập test độc lập, kết quả benchmark và báo cáo giới hạn.
- [ ] Video demo 2-3 phút, README kiến trúc và các bullet CV có số liệu đã đo.

Các ô chưa đánh dấu là phần chưa thực hiện. Không ghi CI/CD hoặc deployment đã thành công khi mới có file cấu hình.
