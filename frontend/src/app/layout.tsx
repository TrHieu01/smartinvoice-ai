import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "SmartInvoice AI — Hiểu rõ từng khoản chi",
  description:
    "Đọc hóa đơn, kiểm tra kết quả AI và quản lý chi tiêu trong một không gian.",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}
