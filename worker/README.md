# RunPod worker

Worker dự kiến chạy trên RunPod Serverless Flex, không yêu cầu máy cá nhân bật OCR.

Input business payload: `../contracts/process-job.schema.json`, chỉ có job_id. Dispatcher bọc payload theo giao thức RunPod, không gửi signed URLs hoặc credential của user trong input. Handler lấy receipt/storage path từ DB sau khi claim lease, tải file bằng server-only credential, chạy pipeline và validate `extraction.schema.json` + Pydantic.

Database là nguồn trạng thái chính. Handler chỉ trả success sau commit; result và job không được cập nhật bằng các REST call rời rạc. Nếu task giao lặp, claim/fencing ngăn xử lý/commit trùng. Provider response thành công không thay thế database transaction.

`handler.py` đã triển khai claim/download/hash và fenced commit; `process.py` chạy pipeline trong subprocess timeout 240s. `pipeline.py` ưu tiên PDF text, ảnh/PDF scan dùng PaddleOCR/OpenCV và rules có source evidence. Model đã được tải và smoke-test CPU local; chưa build Linux image hay tạo endpoint. Không đưa RunPod key vào image/frontend. Cleanup do Edge dispatcher thực hiện. Xem `../docs/deployment.md` về cấu hình phần cứng.
