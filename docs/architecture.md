# Kiến trúc và trạng thái module

- `backend/api`: local REST API + static UI; bind loopback trong `run.sh`.
- `backend/database`: SQLite/WAL cho ảnh, job, annotation và audit history.
- `backend/detection`: YOLO checkpoint validation + optional Transformers Grounding DINO/SAM.
- `backend/consensus`: matching một-một greedy theo IoU, conflict, heuristic tier.
- `backend/pipeline`: worker thread tuần tự, kết quả được commit theo ảnh để resume sau lỗi/restart.
- `backend/dataset`: import, hash trùng, đọc YOLO txt, export immutable snapshot.
- `frontend`: single-page app canvas; UI được phục vụ local bởi FastAPI.

Các model chỉ tải checkpoint được người dùng cấu hình từ filesystem. Dataset image path giữ nguyên trong SQLite; export copy ảnh sang snapshot riêng. `workspace/` chứa database, mask, logs và exports.

## Tầng quality

- `high_agreement`: detector cùng class, IoU đạt ngưỡng, geometry hợp lệ. Pseudo-label, không phải đảm bảo chính xác.
- `needs_review`: một phía phát hiện, class ambiguous/nhỏ hoặc box có warning.
- `high_risk`: class conflict.

`heuristic_score` chỉ để sắp xếp ưu tiên review. Không hiệu chuẩn xác suất. Auto-accept mặc định tắt và export chỉ lấy annotation `accepted=1`.

## Đa nền tảng (0.3)

- `install.py` dùng `venv` mới trên Windows/macOS/Linux, cho phép CPU/GPU/web-only. `setup.sh`/`setup.bat` là wrapper. Không đóng gói `.venv` hoặc dữ liệu máy cũ.
- `backend/core/hardware.py` phát hiện CUDA/ROCm, Apple MPS và CPU; `Auto` chỉ retry CPU khi gặp lỗi GPU/VRAM đã nhận diện.
- `scripts/doctor.py` kiểm tra môi trường và tính toàn vẹn của safetensors.
- `launch.py` chỉ bind loopback trừ khi có opt-in rõ ràng; thay đổi môi trường qua biến `AUTOLABEL_*`.
- `best.pt` và các weights DINO/SAM hợp lệ phải do người dùng cung cấp hoặc tải chính thức; không nhúng weights bị cắt cụt.
- UI gửi device per job. `/api/images/{id}/review` và `/api/images/{id}/annotations` cùng xử lý lưu có kiểm tra tọa độ hợp lệ.

## Lưu ý kiểm nghiệm

Chạy unit/integration tests trên CPU; không khẳng định CUDA/MPS/ROCm đã được smoke test thực tế.
