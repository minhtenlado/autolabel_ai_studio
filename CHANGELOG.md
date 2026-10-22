# AutoLabel AI Studio – 0.3 Portable

## Các thay đổi có thể kiểm tra

- Cài đặt Python venv sạch trên Windows, Linux và macOS: `install.py`, `setup.bat`, `setup.sh`; thêm `--mode web|cpu|auto|gpu`, `--optional` và `--torch-index`.
- Launcher foreground cross-platform (`launch.py`), khởi động nền/dừng Linux (`run.sh`, `stop.sh`), batch cho Windows (`run.bat`). Giữ mặc định bind loopback để bảo vệ API.
- Lớp chọn thiết bị `backend/core/hardware.py`: CPU, CUDA/ROCm, MPS, lựa chọn từng job, khả năng fallback CPU khi accelerator lỗi được nhận diện.
- Sửa UI chọn device; cập nhật CPU preset 640px, CPU/GPU status, đường dẫn model dựa trên máy chạy hiện tại.
- Sửa URL lưu review `/api/images/{id}/review`, bổ sung kiểm tra tọa độ/class khi lưu.
- Không còn auto-accept hàng loạt mọi nhãn có nguy cơ; YOLO-only unverified là tùy chọn opt-in riêng.
- Tránh trùng tên ảnh khi auto-save; chỉ xuất nhãn đã được accept trong kết quả incremental.
- Loại file safetensors cắt cụt, thêm công cụ `scripts/doctor.py` và kiểm tra tensor bounds khi tải về.
- Loại `.venv` và dữ liệu/DB/log từ máy gốc khỏi bản portable; cung cấp mẫu Docker CPU.
- Test: 12 unittest pass, FastAPI integration smoke cho health/import/review/export/pass và fallback GPU OOM giả lập.

## Chưa xác minh

- GPU thật CUDA/ROCm/MPS; chưa có thiết bị GPU tương ứng trong môi trường kiểm thử này.
- YOLO detection thực tế với `best.pt` của người dùng vì bản nguồn không chứa checkpoint này.
- DINO/SAM inference thực tế vì trọng số trong ZIP nguồn là file cắt cụt và cần tải lại.
- Đảm bảo hỗ trợ các hệ thống không có wheel PyTorch/Pillow/Ultralytics tương thích (ví dụ 32-bit, thiết bị nhúng đặc thù).
- Chưa hoàn thiện module TCN 720/180, calibration thực nghiệm hoặc full traffic V2; phạm vi thay đổi ưu tiên khả năng chạy CPU/GPU và độ tin cậy chức năng có sẵn.

**Khi cập nhật project cũ:** sao lưu `workspace/` (DB, masks, exports) và `models/` trước; bản portable này cố ý là gói source sạch. Di chuyển database đơn lẻ không tự sửa đường dẫn ảnh tuyệt đối khi đổi máy; hãy import lại ảnh trên máy đích nếu cần.
