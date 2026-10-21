# Email đăng ký

Supabase Auth gửi email xác nhận qua **Brevo Free**, không dùng SMTP mặc định. Cấu hình đã lưu và kiểm tra lại sau khi reload Dashboard ngày 21/10/2026. Người dùng đã xác nhận nhận được thư, mở xác nhận và đăng nhập thành công trên ứng dụng production.

| Trường | Giá trị |
|---|---|
| Host | `smtp-relay.brevo.com` |
| Port | `465` (SSL) |
| Sender name | `SmartInvoice AI` |
| Sender email | Địa chỉ đã Verified trong Brevo |
| Username | SMTP Login trên trang Brevo SMTP |
| Password | SMTP key, lưu trong Supabase Auth settings |

Không dùng API key hoặc mật khẩu đăng nhập Brevo cho trường SMTP Password. Không đưa SMTP credential vào frontend, Git hoặc logs.

Brevo Free hiện có 300 email/ngày; Supabase custom SMTP mặc định 30 email/giờ. Giữ email confirmation và không mua gói trả phí. Nếu dùng địa chỉ Gmail làm sender, Brevo có thể hiển thị địa chỉ gửi thay thế thuộc brevosend.com.

## Kiểm chứng

Ngày 21/10/2026, Auth logs ghi nhận `/signup` HTTP 200 lúc 09:14:07 và 09:14:35 UTC, `/verify` HTTP 303 lúc 09:14:53 UTC. Người dùng xác nhận nhận email và đăng nhập được. Đây là kiểm chứng gửi email thật, độc lập với smoke test tạo tài khoản bằng Admin API trước đó.

Các bước kiểm tra lại khi thay đổi SMTP:

1. Reload ứng dụng, đăng ký bằng email thật do người kiểm thử sở hữu.
2. Supabase `/signup` trả thành công; Brevo Transactional Logs ghi nhận gửi/delivered.
3. Mở thư xác nhận, kiểm tra redirect về domain production, đăng nhập và truy cập không gian riêng.
4. Không dùng Admin API xác nhận user để thay thế bài kiểm tra gửi email này.

## Thông báo lỗi

`frontend/src/lib/auth-errors.ts` phân biệt giới hạn gửi email, email chưa xác nhận, địa chỉ chưa được chấp nhận và mật khẩu yếu. Không render nguyên văn lỗi provider chứa thông tin người dùng. `npm --prefix frontend test` có ba regression tests; [CI commit c316cc5](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39573826657) đã chạy thành công cùng TypeScript, production build và các kiểm tra backend/database.

Lỗi quan sát ban đầu: `/signup` trả 429 `over_email_send_rate_limit`. Giao diện cũ gộp lỗi này vào thông báo kiểm tra email/mật khẩu; đã sửa ở commit `c316cc5`.

Nguồn: [Brevo SMTP](https://help.brevo.com/hc/en-us/articles/7924908994450-Send-transactional-emails-using-Brevo-SMTP), [Brevo Free](https://help.brevo.com/hc/en-us/articles/208580669-FAQs-What-are-the-limits-of-the-Free-plan), [Supabase SMTP](https://supabase.com/docs/guides/auth/auth-smtp).
