import { createClient, type SupabaseClient } from "@supabase/supabase-js";
export const configured = Boolean(
  process.env.NEXT_PUBLIC_SUPABASE_URL &&
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
);
let client: SupabaseClient | null = null;
export function supabase() {
  if (!configured) throw new Error("Ứng dụng chưa được cấu hình đăng nhập.");
  client ??= createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
  );
  return client;
}
const messages: Record<string, string> = {
  version_conflict: "Hóa đơn đã thay đổi. Hãy tải lại trước khi lưu.",
  receipt_not_found: "Không tìm thấy hóa đơn.",
  quota_exceeded:
    "Đã đạt giới hạn: 20 hóa đơn/ngày và tối đa 3 lượt xử lý cho mỗi hóa đơn.",
  dependency_unavailable:
    "Dịch vụ đang khởi động hoặc tạm gián đoạn. Hãy thử lại sau.",
  service_not_configured: "Máy chủ chưa được cấu hình đầy đủ.",
  invalid_token: "Phiên đăng nhập đã hết hạn. Hãy đăng nhập lại.",
  upload_missing: "File chưa được tải lên thành công. Hãy tải lại file.",
  size_mismatch: "Dung lượng file không khớp. Hãy tạo lượt tải lên mới.",
  unsupported_media_type: "Định dạng file không được hỗ trợ.",
  invalid_file: "File hỏng hoặc không đúng định dạng.",
  too_many_pages: "PDF chỉ được tối đa 5 trang.",
  image_too_large: "Ảnh quá lớn để xử lý. Hãy giảm độ phân giải.",
  invalid_request:
    "Thông tin chưa hợp lệ. Hãy kiểm tra các trường bắt buộc và định dạng số.",
  invalid_state: "Hóa đơn chưa ở trạng thái cho phép thao tác này.",
};
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const base =
    process.env.NEXT_PUBLIC_API_BASE_URL ||
    (process.env.NODE_ENV === "development" ? "http://localhost:8000" : "");
  if (!base)
    throw new Error(
      "Máy chủ xử lý hóa đơn chưa được kết nối. Bạn vẫn có thể xem không gian mẫu.",
    );
  const { data } = await supabase().auth.getSession();
  if (!data.session) throw new Error("Hãy đăng nhập để tiếp tục.");
  let response: Response;
  try {
    response = await fetch(`${base}/api/v1${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${data.session.access_token}`,
        ...init.headers,
      },
      cache: "no-store",
      signal: AbortSignal.timeout(90000),
    });
  } catch {
    throw new Error(
      "Chưa kết nối được máy chủ. Dịch vụ có thể đang khởi động; hãy thử lại.",
    );
  }
  const result = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(
      messages[result.error?.code] ??
        "Không thực hiện được yêu cầu. Hãy thử lại.",
    );
  return result as T;
}
export type Item = {
  line_number: number;
  name: string;
  quantity: string | null;
  unit_price: string | null;
  line_total: string | null;
};
export type Data = {
  merchant: string | null;
  merchant_tax_id: string | null;
  invoice_number: string | null;
  purchase_date: string | null;
  subtotal: string | null;
  tax_amount: string | null;
  discount_amount: string | null;
  total_amount: string | null;
  currency: "VND" | null;
  items: Item[];
};
export type Summary = {
  id: string;
  filename: string;
  status: string;
  merchant: string | null;
  purchase_date: string | null;
  total_amount: string | null;
  currency: "VND" | null;
  category: string;
  version: number;
  created_at: string;
  updated_at: string;
};
export type Warning = {
  code: string;
  message: string;
  field: string | null;
  severity: string;
};
export type Detail = Summary & {
  data: Data;
  warnings: Warning[];
  job: { error_code: string | null } | null;
  latest_extraction: {
    evidence: { field: string; line_ids: string[] }[];
    ocr: {
      pages: {
        page_number: number;
        lines: {
          id: string;
          text: string;
          bbox: { x0: number; y0: number; x1: number; y1: number };
        }[];
      }[];
    };
  } | null;
};
export type ReceiptList = {
  items: Summary[];
  page: number;
  page_size: number;
  total_count: number;
};
export type Analytics = {
  total_amount: string;
  receipt_count: number;
  monthly: { month: string; total_amount: string; receipt_count: number }[];
  categories: {
    category: string;
    total_amount: string;
    receipt_count: number;
  }[];
};
export const categories: Record<string, string> = {
  uncategorized: "Chưa phân loại",
  food: "Ăn uống",
  shopping: "Mua sắm",
  transport: "Di chuyển",
  utilities: "Tiện ích",
  health: "Sức khỏe",
  education: "Học tập",
  other: "Khác",
};
export const statusNames: Record<string, string> = {
  awaiting_upload: "Chờ tải file",
  queued: "Đang chờ",
  processing: "Đang đọc",
  needs_review: "Cần kiểm tra",
  confirmed: "Đã xác nhận",
  failed: "Xử lý lỗi",
  deleting: "Đang xóa",
};
export const formatMoney = (value: string | number | null) =>
  value === null
    ? "—"
    : new Intl.NumberFormat("vi-VN", {
        style: "currency",
        currency: "VND",
        maximumFractionDigits: 0,
      }).format(Number(value));
export const formatDate = (value: string | null) =>
  value
    ? new Date(value + "T12:00:00").toLocaleDateString("vi-VN")
    : "Chưa xác định";
