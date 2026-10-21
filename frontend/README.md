# SmartInvoice frontend

Đã có Next.js + TypeScript + Tailwind và các component dùng HTML native/lucide. Chạy `npm ci`, `npm run dev`; build `npm run build` dùng Webpack. Chưa tích hợp shadcn/ui.

Contract API: `../contracts/openapi.json`. Auth dùng Supabase, publishable key ở browser; server secret/RunPod key không được có trong NEXT_PUBLIC_*.

Năm màn hình: Authentication, Dashboard, Upload, Receipt Review, History. Review dùng data hiện tại để chỉnh sửa, latest_extraction để hiện bằng chứng gốc. Signed preview tự refresh sau 240s. Chế độ mẫu chỉ để xem và được gắn nhãn; worker lỗi không được thay bằng dữ liệu mẫu.

Đã deploy Vercel Hobby tại https://smartinvoice-ai-coral.vercel.app, kết nối API Render Free. Public env được nhúng lúc build, thay đổi cần redeploy. Brevo Free SMTP đã kiểm chứng luồng đăng ký, nhận email xác nhận và đăng nhập; sample mode không cần tài khoản.
