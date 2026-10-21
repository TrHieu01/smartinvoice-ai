# RunPod worker

Pipeline `rules-0.3.0` bổ sung parser theo bố cục cho bảng/thẻ sản phẩm nhiều dòng, số chứng từ, tổng tiền và loại thanh trạng thái khỏi tên cửa hàng. Xem [kiểm chứng và giới hạn](../docs/extraction.md). Kết quả cũ không tự cập nhật; cần upload file thành hóa đơn mới sau khi endpoint dùng image mới.

Worker dự kiến chạy trên RunPod Serverless Flex, không yêu cầu máy cá nhân bật OCR.

Input business payload: `../contracts/process-job.schema.json`, chỉ có job_id. Dispatcher bọc payload theo giao thức RunPod, không gửi signed URLs hoặc credential của user trong input. Handler lấy receipt/storage path từ DB sau khi claim lease, tải file bằng server-only credential, chạy pipeline và validate `extraction.schema.json` + Pydantic.

Database là nguồn trạng thái chính. Handler chỉ trả success sau commit; result và job không được cập nhật bằng các REST call rời rạc. Nếu task giao lặp, claim/fencing ngăn xử lý/commit trùng. Provider response thành công không thay thế database transaction.

`handler.py` là async handler tương thích event loop RunPod SDK, thực hiện claim/download/hash và fenced commit; `process.py` chạy pipeline trong subprocess timeout 240s. `pipeline.py` ưu tiên PDF text, ảnh/PDF scan dùng PaddleOCR/OpenCV và rules có source evidence. Linux image đã build trên GitHub Actions và endpoint CPU 2 vCPU/8 GB đã tạo; xem `../docs/verification.md` cho kết quả thực tế. Không đưa RunPod key vào image/frontend. Cleanup do Edge dispatcher thực hiện. Xem `../docs/deployment.md` về cấu hình phần cứng.
