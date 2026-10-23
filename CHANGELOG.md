# AutoLabel AI Studio

## 0.4.0 — 2026-10-23

- Thiết kế lại giao diện tiếng Việt: quy trình 4 bước, dashboard dữ liệu thật, dark mode, điều hướng mobile đầy đủ, tìm kiếm/phân trang/thumbnail, trạng thái rỗng và tiến độ tác vụ.
- Editor có undo/redo, vẽ box mọi hướng, resize/pan/zoom, lớp evidence, dirty guard, lưu & ảnh tiếp, lịch sử và xác nhận negative. Lưu qua phiên bản ảnh để ngăn tab cũ ghi đè; không mất metadata DINO/SAM.
- Migration schema v4 có backup; import kiểm tra trước clear, giữ ID ảnh tăng sau thay dataset, kiểm tra ảnh/nhãn đầy đủ, hỗ trợ cấu trúc YOLO lồng nhau và tên lớp trong data.yaml. Tùy chọn giữ frame trùng khác thời điểm.
- Task nền có progress cho import/export/traffic; khóa phối hợp với worker và review. Job có danh sách ảnh bền vững, stop/cancel riêng, pause/resume/retry/restart giữ đúng tiến độ; bảo vệ nhãn gốc và thủ công.
- Lưu incremental thành JSON proposals, không tạo nhãn âm tính giả. Export detection chỉ dữ liệu đủ điều kiện, pseudo-label opt-in; snapshot không ghi đè, manifest, lịch sử và ZIP. Split camera/ngày, gộp nhóm trùng SHA-256 để tránh trùng nội dung train/val.
- ROI vẽ trực quan và calibration; exclusion và box human-rejected được loại khỏi thống kê. Phân tích lại giữ nhãn classification người đã duyệt; đặc trưng stale phải cập nhật trước CSV. Xuất toàn bộ chuỗi, không cắt ở 2.000 hàng.
- Bỏ frontend/dist trùng, tách module frontend và giữ không cần build. Validation checkpoint detection và geometry hữu hạn; bổ sung đồng bộ EXIF, download theo export ID và chặn ghi khác origin.
- 47 unit/API/worker tests và 15 nhóm kiểm tra trình duyệt trên desktop/mobile. Chưa chạy weights thật, GPU, Docker hoặc Windows/macOS thực tế. Không có benchmark khẳng định tăng độ chính xác AI.
- Bổ sung form thực thi, báo cáo audit, hướng dẫn migration/API và tài liệu kiến trúc.

## 0.3 Portable — lịch sử

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
