import type { Analytics, Detail, Summary } from "./client";
const now = "2026-10-21T08:00:00Z";
export const samples: Summary[] = [
  ["Cộng Cà Phê", "2026-10-21", "145000", "food", "needs_review"],
  ["MUJI Việt Nam", "2026-10-20", "489000", "shopping", "confirmed"],
  ["Grab", "2026-10-19", "78000", "transport", "confirmed"],
  ["Phúc Long", "2026-10-18", "125000", "food", "confirmed"],
].map(([merchant, purchase_date, total_amount, category, status], index) => ({
  id: `sample-${index}`,
  merchant,
  purchase_date,
  total_amount,
  currency: "VND",
  category,
  status,
  filename: "hoa-don-mau.pdf",
  version: 1,
  created_at: now,
  updated_at: now,
}));
export const sampleAnalytics: Analytics = {
  total_amount: "692000",
  receipt_count: 3,
  monthly: [
    { month: "2026-08", total_amount: "0", receipt_count: 0 },
    { month: "2026-09", total_amount: "0", receipt_count: 0 },
    { month: "2026-10", total_amount: "692000", receipt_count: 3 },
  ],
  categories: [
    { category: "shopping", total_amount: "489000", receipt_count: 1 },
    { category: "food", total_amount: "125000", receipt_count: 1 },
    { category: "transport", total_amount: "78000", receipt_count: 1 },
  ],
};
export function sampleDetail(row: Summary): Detail {
  return {
    ...row,
    job: null,
    latest_extraction: null,
    warnings: [
      {
        code: "missing_field",
        severity: "warning",
        field: "/merchant_tax_id",
        message: "Ví dụ minh họa: kiểm tra thông tin trước khi xác nhận.",
      },
    ],
    data: {
      merchant: row.merchant,
      merchant_address: "12 Đường Mẫu, TP. Hồ Chí Minh",
      payment_method: "Tiền mặt",
      purchase_date: row.purchase_date,
      total_amount: row.total_amount,
      currency: "VND",
      merchant_tax_id: null,
      invoice_number: "DEMO-001",
      subtotal: row.total_amount,
      tax_amount: null,
      discount_amount: null,
      items: [{
        line_number: 1,
        name: "Sản phẩm minh họa",
        unit: "phần",
        quantity: "1",
        unit_price: row.total_amount,
        line_total: row.total_amount,
      }],
    },
  };
}
