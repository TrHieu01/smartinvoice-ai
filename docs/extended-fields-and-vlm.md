# Cập nhật production — 26/10/2026

Qwen3-VL-4B đã bật trên endpoint GPU `smartinvoice-vlm`, active=0/max=1; CPU endpoint riêng max=0. Server handler xử lý job thật, dispatcher v5 chỉ dùng key của GPU. Ảnh PNG/JPEG Việt tổng hợp đã qua pipeline `rules-0.4.1+qwen3vl4b` và toàn bộ luồng review/analytics. Ba lượt PDF text vẫn fallback do citation OCR rỗng; adapter không chấp nhận giá trị không có nguồn hợp lệ. Hai bản sửa chuẩn hóa JSON và khôi phục citation scalar khớp baseline đã có regression tests, nhưng chưa giải quyết mọi citation thiếu của Qwen. Đây chưa phải benchmark hóa đơn thực. Chi tiết hiện hành ở [kiểm chứng](verification.md); các phiên GPU tắt bên dưới là lịch sử ngày 21/10.

---

# Trường bổ sung và thử nghiệm mô hình đọc ảnh

## Các trường mới

| Trường | API | Giới hạn |
|---|---|---|
| Đơn vị tính sản phẩm | `items[].unit` | Text 1–50 ký tự hoặc null |
| Địa chỉ cửa hàng | `merchant_address` | Text 1–500 ký tự hoặc null |
| Phương thức thanh toán | `payment_method` | Text 1–50 ký tự hoặc null |

Các trường đều không bắt buộc. Pydantic nhận được dữ liệu cũ thiếu các trường này và trả null. Worker mới xuất schema 1.1.0; API/database vẫn đọc schema 1.0.0. Không tự sửa kết quả hóa đơn cũ.

Rules hỗ trợ đơn vị trong cột ĐVT hoặc dấu ngoặc cuối tên như `(KG)`, `(HỘP)`. Không suy ra đơn vị bán từ mô tả lốc/hộp hoặc trọng lượng đóng gói. Địa chỉ chỉ lấy từ dòng có nhãn/đường rõ và phần tiếp nối gần nhau; không lấy địa chỉ giao hàng. Thanh toán hỗ trợ tiền mặt/thẻ/chuyển khoản/ví điện tử khi có nhãn rõ; nhiều phương thức khác nhau thì cảnh báo, không chọn bừa.

API, database RPC, lịch sử chỉnh sửa, form và source evidence đều hỗ trợ ba trường. Migration chỉ thêm cột nullable và thay các RPC hiện có, giữ SECURITY INVOKER, ownership checks, RLS và quyền gọi server-only. Triển khai API trước migration, giao diện/worker sau.

## Mô hình GPU chuẩn bị thử

Ứng viên là [Qwen3-VL-4B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct), Apache 2.0, pin revision `ebb281ec70b05090aa6165b016eac8ec08e71b17`. Chưa khẳng định tốt hơn PaddleOCR trên hóa đơn Việt trước khi đo.

- CPU production mặc định `EXTRACTION_BACKEND=rules`; thêm code không tự bật GPU.
- GPU image riêng `worker/Dockerfile.vlm`, workflow thủ công **Build experimental VLM worker image**; PyTorch/Transformers/Accelerate được khóa trong uv.lock.
- Model đọc ảnh và OCR regions, trả JSON gồm data + evidence. Không chạy công cụ hoặc thực thi nội dung hóa đơn.
- Kiểm tra schema, dòng nguồn, đường dẫn field, số tiền/ngày, trùng evidence. Phản hồi không hợp lệ/lỗi GPU trả về rules baseline với cảnh báo; không ghi raw model output hoặc lỗi có nội dung riêng tư vào UI/logs.
- Thiếu năm/ngoại tệ được rules phát hiện không bị model tự điền. Kiểm tra phép tính vẫn chạy; luôn human review.
- Giới hạn 5 trang theo app; prompt tối đa 100 OCR regions, context 14.000 tokens, output 4.096 tokens, generation 150s, subprocess 240s. Tài liệu dài/phức tạp có thể fallback; không coi JSON hợp lệ là bảo đảm dữ liệu đúng.

## Đề xuất lượt thử cần chốt ngân sách

Ngân sách riêng đã được duyệt ngày 21/10/2026; trạng thái lượt thử và endpoint được ghi bên dưới.

Đề xuất endpoint thử `smartinvoice-vlm`, GPU 24 GB (ưu tiên L4/A5000/3090), active=0, max=1, idle=5s, execution=300s, container disk 40 GB, không network volume. Giữ endpoint CPU hiện có làm đường lui. API key mới chỉ GET/POST endpoint thử, chỉ lưu phía server.

Đã duyệt tối đa **0,50 USD từ credit hiện có** cho tối đa 3 hóa đơn thử; không nạp tiền/nâng gói và không chuyển traffic production sang GPU tự động. Giá công khai ngày 21/10/2026 cho nhóm Serverless 24 GB là khoảng $0,69/giờ GPU; chi phí còn phụ thuộc initialization, thời gian chạy, idle và disk. [Giá RunPod](https://www.runpod.io/pricing), [cách tính khi job lỗi](https://www.runpod.io/blog/failed-requests-real-charges-how-runpod-serverless-billing-works-when-workers-fail).

Đây là giới hạn chi tiêu do phiên thử theo dõi, không phải hard cap tự động của RunPod. Không gửi thêm job nếu chi phí không còn đủ; kết thúc lượt thử phải dừng GPU rồi xác nhận worker đã ngừng. Đo đúng theo từng trường/sản phẩm, thời gian và chi phí, đối chiếu baseline trước khi quyết định dùng lâu dài.

## Image thử đã build

[Build 75ab41d](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39588380711) thành công; package public và anonymous manifest HTTP 200. Image pin:

```text
ghcr.io/trhieu01/smartinvoice-ai-worker-vlm@sha256:7259fbf7326319360cb6cc19810e5b00b7e1ce2f55c9579f20f15eb92a40a581
```

Weights và processor được nạp sẵn; CPU build đã kiểm tra processor nhận ảnh giả lập. Đây chưa phải kiểm chứng inference hay chất lượng trích xuất GPU. Candidate dùng baseline rules-0.4.0; production CPU dùng rules-0.4.1 với guard địa chỉ người nhận bổ sung. Adapter VLM không thay đổi giữa hai bản.

## Lượt thử GPU đầu — 21/10/2026

Người dùng đã duyệt tối đa 0,50 USD credit cho phiên thử, tối đa 3 hóa đơn; không tự chuyển production sang GPU. Endpoint riêng `smartinvoice-vlm` (`dvaal7yuostlnu`), key Restricted chỉ GET/POST endpoint này, GraphQL/CPU endpoint không có quyền. Key chỉ lưu ở Supabase Edge Secret `RUNPOD_VLM_TRIAL_API_KEY`.

Một ảnh tổng hợp tiếng Việt có hai sản phẩm được gửi riêng, không qua dispatcher production. Kết quả DB thành công sau 64.832 ms (OCR 12.948 ms; extraction gồm VLM 51.843 ms), pipeline `rules-0.4.0+vlm-fallback`. Rules giữ đúng hai dòng sản phẩm và tổng 99.000 VND, nhưng còn sai dấu tên/ĐVT và thiếu thuế, địa chỉ, thanh toán. Chưa thể kết luận Qwen cải thiện chất lượng vì đầu ra không vượt qua validation và phải fallback.

RunPod đã retry một lần sau khi DB lưu thành công; invocation sau trả terminal theo thiết kế idempotency. Log có lỗi ghi `.runpod_jobs.pkl.lock` tại `/app` của non-root user. Commit `49dc539` sửa quyền ghi thư mục này và bổ sung chẩn đoán fallback bằng stage/reason cố định; không chuyển tiếp raw stderr, exception text hay nội dung hóa đơn. 74 pytest và Ruff qua; [CI 49dc539](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39617070513) thành công. GPU đặt active=0/max=0, không còn worker trong khi build bản kiểm chứng. Billing dashboard có độ trễ; không coi số hiển thị tức thì là chi phí cuối.

Bản chẩn đoán [build 39617176771](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39617176771) đã thành công, anonymous GHCR manifest HTTP 200, digest `sha256:72fdb85e331744f50b4a246920bc6bd8ba4281b43a7a24adbb86a1b2541820d0`. Đã cập nhật endpoint thử. Hóa đơn needs_review không được quay lại queued; lượt kiểm chứng tiếp theo dùng bản sao tổng hợp và job mới, giữ nguyên state machine. Job nháp chưa chạy của mẫu cũ đã hủy bằng command si_delete chuẩn.

## Lượt kiểm chứng thứ hai

Worker RTX A5000 với image `72fdb85e…` hoàn tất và lưu kết quả ngay lần đầu, provider không báo retry. Queue 354.853 ms, execution 50.917 ms; pipeline total 44.576 ms (OCR 8.593 ms, extraction/VLM 35.946 ms). Log cố định xác định `stage=decode reason=schema`. Đây là lỗi hợp lệ hóa đầu ra, chưa đủ dữ liệu kết luận năng lực đọc ảnh của model.

Hai tài khoản và hóa đơn tổng hợp của lượt 1–2 đã dọn; xác minh metadata/prefix email và đúng storage UUID trước cleanup. Không thay hóa đơn/tài khoản thật.

`worker.benchmark` là entry point riêng chỉ chấp nhận `{"fixture":"synthetic-receipt-v1"}`. Fixture PNG được pin SHA-256; từ chối file, URL hoặc job ID từ bên ngoài. Chỉ entry point này trả raw model output của ảnh tổng hợp trong response RunPod riêng, không ghi output vào logs và không truy cập Supabase. Handler production không đổi giao thức/không trả raw model output. 76 pytest và [CI ec0c653](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39621232236) thành công.

Image benchmark [build 39621299298](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39621299298) thành công: `sha256:f6b1ab49f4c097923e0f15c13cde28b69f9c86d832d95592f8c0cef0951174a8`, anonymous manifest HTTP 200. Build code-only kế thừa model layers từ digest 49dc539 đã xác minh và so sánh cả pyproject.toml/uv.lock; dependency thay đổi phải dùng full build. Default CMD vẫn là worker.handler; endpoint thử override `python -u -m worker.benchmark` cho lượt cuối và đã bỏ Supabase env/secret.

CPU production đã Ready với image `sha256:afb7295ca4af7f54fb52a6cbeae66b56df6a24b52e61a1a1c00d2a10b6daeaba` (commit ec0c653), cùng parser rules-0.4.1, active=0/max=1/idle=5s. [Build CPU](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39622064984). Không chuyển dispatcher production sang GPU.

## Kết quả lượt cuối và sửa adapter

Lượt thứ ba chạy fixture đóng sẵn, không có Supabase env/secret. Provider COMPLETED, queue 160.665 ms, execution 51.485 ms; pipeline 51.295 ms. Đã gửi đủ 3 lượt thử model trong phiên và không gọi thêm GPU sau đó.

Đầu ra ghi nhận (`contracts/examples/vlm.synthetic.raw.json`) đọc được Sữa tươi/hộp, Táo đỏ/kg, thuế 9.000, tổng 99.000 và Tiền mặt. Lỗi tích hợp gồm tiền còn dấu phân cách hàng nghìn, evidence có prefix /data/, evidence rỗng cho giá trị null và evidence của line_number. Adapter bổ sung chuẩn hóa có giới hạn: chỉ nhóm ba chữ số khi cả OCR baseline và output model xác định currency VND; giữ nguyên decimal hợp lệ, số lượng thập phân, giá trị sai số học và cảnh báo; bỏ prefix /data/; không đòi bằng chứng cho null/ordinal. Nguồn không tồn tại, đường dẫn lạ, thiếu nguồn cho giá trị thật hoặc nguồn trùng vẫn bị từ chối. Prompt bổ sung ví dụ chuẩn.

Đã replay bằng chính output GPU ghi nhận, PNG có hash cố định và OCR CPU local dùng cùng Paddle models (23 vùng). Baseline local được lưu riêng ở `contracts/examples/vlm.synthetic.baseline.json`; đây không phải baseline tải đầy đủ từ RunPod. Kết quả full ExtractionResult hợp lệ, pipeline +qwen3vl4b, hai tên/ĐVT đúng, tiền hàng 90.000 + thuế 9.000 = 99.000 và có source IDs hợp lệ. Địa chỉ model vẫn đọc Minh Hoa thay vì Minh Họa: human review vẫn cần thiết. 92 pytest qua, gồm replay và các ca giữ cảnh báo tổng tiền sai. Chưa chạy GPU thêm sau khi sửa adapter; không dùng mẫu tổng hợp này để công bố accuracy trên hóa đơn thực.

RunPod balance UI từ 14,60 xuống 14,55 USD trong phiên, delta khoảng 0,05 USD, thấp hơn mức được duyệt 0,50 USD. Đây là số làm tròn của tài khoản, có độ trễ billing và có thể bao gồm hoạt động CPU khác; không phải chi phí GPU quyết toán riêng chính xác. GPU được đặt active=0/max=0 sau lượt cuối; production vẫn route CPU.

Cơ chế lấy kết quả qua Edge Function tạm đã bị automatic approval review chặn và không được deploy. Không tạo endpoint API mới cho việc đọc benchmark. Kiểm chứng được hoàn thành bằng output đọc từ giao diện và replay offline.

## Artifact cuối phiên

[CI 87c11d1](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39626302843) thành công với 92 pytest, 14 SQL tests, 3 frontend Auth tests và build/check khác. [GPU build 39626330921](https://github.com/TrHieu01/smartinvoice-ai/actions/runs/39626330921) thành công, anonymous GHCR manifest HTTP 200. Candidate đã lưu vào endpoint đang tắt:

```text
ghcr.io/trhieu01/smartinvoice-ai-worker-vlm@sha256:87127650406e07c6ecf15ac5f35ab57afe8015f429c76652783e616568e374a4
```

Endpoint vẫn active=0/max=0, override worker.benchmark chỉ đọc fixture, không có Supabase env/secret. Image mặc định chứa worker.handler cho tích hợp sau khi có ngân sách vận hành phù hợp; chưa đổi routing production. Không chạy GPU thêm để xác minh image cuối; thay đổi adapter được kiểm chứng bằng replay, unit tests và CI/build. Frontend HTTP 200, API health ok/OpenAPI 1.1.0 có đủ ba trường mới.
