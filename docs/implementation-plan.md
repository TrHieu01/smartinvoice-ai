# Các mốc triển khai SmartInvoice AI

Trạng thái runtime/triển khai mới nhất: xem [verification.md](verification.md). Checklist dưới đây được lập ở mốc thiết kế; các phần đang còn cần bổ sung được tách rõ.

## Mốc 1 - Contracts

- [x] Database schema, constraints, RLS và private bucket migration.
- [x] Public OpenAPI và JSON Schema AI/job payload.
- [x] Pydantic source, ví dụ và drift check.
- [x] Test SQL thực trên PostgreSQL/WASM và test schema/OpenAPI.
- [x] Nghiên cứu nền tảng Free, tách riêng compute RunPod credit.
- [x] CI definition cho mốc contract; chưa có GitHub run thật.

## Mốc 2 - Backend và Supabase integration

- [x] FastAPI cấu hình, Auth token verification, CORS allowlist và lỗi thống nhất.
- [x] Atomic server-only RPC: create/submit/retry/claim/complete/review/delete; tenant checks.
- [x] Signed upload, kiểm chứng object và quota app.
- [ ] API tests với 2 người dùng; unauthorized ID, concurrency, stale version.
- [x] Supabase Free thật để test Auth/Storage HTTP và advisors.

## Mốc 3 - AI worker và RunPod adapter

- [x] PDF text extraction + fallback OCR, kiểm tra trang/pixel/định dạng.
- [x] PaddleOCR vi/en + OpenCV, rules và validation bằng Decimal.
- [x] Handler nhận job_id, lease/fencing và commit nguyên tử.
- [ ] Container với dependency/model version pin rõ, benchmark CPU/GPU.
- [x] Supabase Edge dispatcher + lease, provider request ID, bounded retries.
- [ ] Cron reconciliation/cleanup; secret trong Vault, không public quyền tiêu credit.
- [ ] Chuẩn bị cấu hình Serverless: active=0, max=1 và execution timeout; chưa tạo endpoint.

## Mốc 4 - Frontend

- [ ] Next.js/TypeScript/Tailwind + shadcn/ui; type sinh từ OpenAPI.
- [x] Auth, Dashboard, Upload, Review và History.
- [x] Review cạnh ảnh/PDF, evidence highlight, source/original AI và editable data tách rõ.
- [ ] Polling backoff, lỗi cold start/quota/credit và optimistic concurrency.
- [ ] Responsive/accessibility; test upload -> process -> review -> analytics.

## Mốc 5 - Demo và portfolio

- [ ] Tạo repository, bật CI và xác minh run thật.
- [ ] Build/test containers và frontend; deploy Vercel Hobby + Render Free + Supabase Free.
- [ ] Tạo RunPod endpoint từ image/config đã kiểm tra, trong phạm vi sử dụng credit được cấp phép.
- [ ] Smoke tests, monitoring, lỗi mẫu và kiểm tra không log dữ liệu hóa đơn.
- [ ] Tập test độc lập, kết quả benchmark và báo cáo giới hạn.
- [ ] Video demo 2-3 phút, README kiến trúc và các bullet CV có số liệu đã đo.

Các ô chưa đánh dấu là phần chưa thực hiện. Không ghi CI/CD hoặc deployment đã thành công khi mới có file cấu hình.
