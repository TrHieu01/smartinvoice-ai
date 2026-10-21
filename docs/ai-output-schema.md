# AI Output Schema v1.0.0

Nguồn Python: `backend/app/schemas/contracts.py`. File portable: `contracts/extraction.schema.json` (JSON Schema 2020-12). Ví dụ giả lập: `contracts/examples/extraction.vi.json`.

## Envelope

| Trường | Ý nghĩa |
| --- | --- |
| schema_version | Version định dạng, hiện 1.0.0 |
| receipt_id / job_id | UUID lấy từ database, không do model đoán |
| pipeline_version | Version cấu hình OCR/rules/model, ghi rõ cấu hình đang dùng |
| processed_at | Timestamp UTC có timezone |
| data | Thông tin trích xuất, null nếu không có bằng chứng |
| ocr | Engine/version, languages, pages và text lines với tọa độ |
| evidence | Ánh xạ JSON Pointer tới các OCR line ID |
| warnings | Validation kết quả, không ghi đè dữ liệu gốc |
| timings | Thời gian từng stage và end-to-end, millisecond |

## Dữ liệu chính

`merchant`, `merchant_tax_id`, `invoice_number`, `purchase_date`, `subtotal`, `tax_amount`, `discount_amount`, `total_amount`, `currency`, `items` đều có mặt trong JSON. Những scalar không đọc được là null; không tìm thấy bảng hàng hóa thì items = []. Không dùng chuỗi rỗng, số 0 hay ngày upload để thay thông tin thiếu.

Tiền là chuỗi số canonical, dấu chấm cho phần thập phân, không có dấu phân tách hàng nghìn, tối đa 14 chữ số nguyên và 2 chữ số lẻ. Quantity tối đa 3 chữ số lẻ và >0. Backend dùng Decimal. Date phải là ngày ISO có thật, không nhận epoch hoặc ngày nhập nhằng.

Currency chỉ VND hoặc null trong MVP. Khi nguồn ghi tiền khác, để currency null và thêm unsupported_currency; không tự quy đổi. Hóa đơn âm/hoàn tiền không thuộc v1.

Items gồm line_number duy nhất, name và quantity/unit_price/line_total có thể null. Giữ line_number khi review để so với dòng AI ban đầu; OCR evidence của kết quả gốc vẫn dùng array index gốc.

## OCR và evidence

Pages đánh số liên tục 1..5, mỗi line có ID `p1-l1`, text, bbox và source. Bbox `(x0,y0,x1,y1)` chuẩn hóa 0..1 trên trang đã sửa hướng. Cần x0<x1, y0<y1. Preview được tạo trên cùng coordinate space; không highlight tọa độ đã sửa góc lên ảnh gốc chưa transform.

`source=pdf_text` khi lấy text layer trực tiếp, `source=paddleocr` khi nhận dạng ảnh. Confidence OCR là số 0..1 nếu engine cung cấp, PDF text để null. Đây không phải xác suất giá trị merchant/total đúng.

Mỗi trường trích xuất khác null phải có một FieldEvidence chứa JSON Pointer và line_ids tồn tại. Ví dụ `/total_amount` hoặc `/items/0/name`. Không được gắn evidence vào trường null, trỏ đến dòng không có thật hay tự bịa source text.

Pydantic kiểm tra các ràng buộc liên trường (unique line_number, evidence trỏ đúng dữ liệu, pages liên tục); JSON Schema hỗ trợ cấu trúc/kiểu dữ liệu portable. Worker phải chạy Pydantic validation đầy đủ, không chỉ kiểm tra JSON parse thành công.

## Validation khi triển khai pipeline

1. Chuẩn hóa dấu phân tách tiền theo ngữ cảnh VN/EN; trường nhập nhằng giữ null hoặc warning, không đoán âm thầm.
2. Kiểm tra merchant/date/total/currency bị thiếu -> missing_field.
3. Nếu có đủ các thành phần, so tổng thanh toán với subtotal + tax - discount, tolerance 1 VND. Thành phần không biết giữ null; không tự coi null là 0.
4. Đối chiếu quantity * unit_price với line_total nếu đủ dữ liệu; chênh lệch -> item_total_mismatch.
5. Chỉ so tổng items với subtotal khi xác định đã lấy đủ bảng hàng; bảng bị cắt không được dùng để sửa tổng tiền.
6. OCR kém -> low_ocr_confidence; nhiều giá trị cạnh tranh -> ambiguous_value. Toàn bộ text rỗng -> empty_document.

Warnings có code, severity, field và message. Severity error biểu thị kết quả cần kiểm tra, không phải lý do ghi đè số tiền nguồn. Kết quả parse/schema hỏng không lưu như thành công; job ghi failed với error_code phù hợp.

Baseline là OCR + rules. Nếu thử LLM sau này, giữ cùng schema và evidence; instruction trong hóa đơn là nội dung dữ liệu, không phải lệnh cho model. LLM không tự xác nhận receipt hoặc gọi tools.

## Human review và metrics

Kết quả AI gốc lưu bất biến trong extraction_results; receipt/items là dữ liệu hiện tại sau review. receipt_corrections lưu cả confirm không sửa trường nào để không mất mẫu đúng trong thống kê.

`timings` của ví dụ fixture là 0 vì không chạy model. Không dùng fixture làm kết quả benchmark.

## Đánh giá

Tạo tập ground truth riêng, tách theo nhà cung cấp/bố cục để tránh cùng template xuất hiện ở cả bộ phát triển và test. Ghi provenance/license và ẩn thông tin cá nhân. Dữ liệu giả lập chỉ phục vụ kiểm tra giao thức/UI; báo cáo riêng với hóa đơn thực.

| Nhóm | Metric và cách đo |
| --- | --- |
| OCR | CER/WER trên text đã gán nhãn; báo cáo riêng vi/en, ảnh/PDF |
| Header fields | Exact match sau chuẩn hóa, từng trường và toàn bộ các trường bắt buộc |
| Items | Precision/recall/F1 theo row matching đã định nghĩa, không chỉ đếm số dòng |
| Validation | Tỷ lệ phát hiện tổng sai và false-positive trên ground truth |
| Performance | P50/P95 stage/end-to-end, cold start và warm run tách riêng; ghi hardware/model version |
| Review | Observed correction rate theo trường ở lần confirm đầu tiên mỗi receipt |

Correction rate = số trường được sửa so với AI baseline / số trường được người dùng review. Chuẩn hóa Decimal/date trước so sánh; category không phải output AI nên không đưa vào mẫu số. Null được người dùng điền là correction, không bỏ qua. Không coi mọi receipt chưa review là đúng, không tính lại nhiều lần confirm như nhiều hóa đơn độc lập. Đây là metric hành vi review có selection bias, không thay thế accuracy từ tập test độc lập.

Chưa có benchmark OCR/extraction trong mốc contract này. Chỉ đặt mục tiêu hiệu năng sau khi pipeline và tập test tồn tại.
