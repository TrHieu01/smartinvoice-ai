type AuthFailure = { code?: string; status?: number };

/** Use stable provider codes; never render raw errors containing user data. */
export function authErrorMessage(error: AuthFailure, signup: boolean): string {
  const messages: Record<string, string> = {
    over_email_send_rate_limit:
      "Đã chạm giới hạn gửi email xác nhận. Vui lòng chờ rồi thử lại; nếu đã nhận thư xác nhận trước đó, hãy mở thư đó.",
    over_request_rate_limit:
      "Bạn đã gửi quá nhiều yêu cầu. Vui lòng chờ rồi thử lại.",
    email_address_not_authorized:
      "Email này chưa được phép nhận thư xác nhận trong cấu hình hiện tại. Ứng dụng cần hoàn tất cấu hình gửi email riêng.",
    email_address_invalid:
      "Địa chỉ email chưa được dịch vụ chấp nhận. Hãy kiểm tra lại địa chỉ; nếu địa chỉ đúng, cấu hình gửi email của ứng dụng có thể chưa sẵn sàng.",
    email_not_confirmed:
      "Hãy mở email xác nhận để kích hoạt tài khoản trước khi đăng nhập.",
    weak_password:
      "Mật khẩu chưa đủ mạnh. Dùng ít nhất 8 ký tự và tránh mật khẩu phổ biến.",
    invalid_credentials:
      "Chưa đăng nhập được. Hãy kiểm tra email, mật khẩu và xác nhận email của bạn.",
    signup_disabled: "Tính năng đăng ký đang tạm đóng. Vui lòng thử lại sau.",
    email_provider_disabled:
      "Đăng nhập bằng email đang tạm đóng. Bạn có thể xem không gian mẫu bên dưới.",
  };
  if (error.code && messages[error.code]) return messages[error.code];
  if (error.status === 429) return messages.over_request_rate_limit;
  return signup
    ? "Chưa tạo được tài khoản. Dịch vụ đăng ký có thể đang gián đoạn; vui lòng thử lại sau."
    : messages.invalid_credentials;
}
