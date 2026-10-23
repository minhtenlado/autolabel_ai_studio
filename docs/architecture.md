# Kiến trúc AutoLabel AI Studio 0.4

Một FastAPI process phục vụ REST và static `frontend/`, một SQLite WAL workspace, một inference worker tuần tự. Review và export hoạt động trong chế độ web không cần Torch. Launcher giữ bind loopback; đây chưa phải dịch vụ nhiều người dùng.

| Module | Trách nhiệm |
|---|---|
| `backend/api/app.py` | Validation request, optimistic review version, điều phối mutation, API task/job/export, ảnh chuẩn EXIF và thumbnail |
| `backend/database/store.py` | Schema v4, backup trước migration, transaction, khôi phục trạng thái job/task khi restart |
| `backend/core/tasks.py` | Tác vụ maintenance nền/đồng bộ, progress và result bền vững trong SQLite |
| `backend/pipeline/worker.py` | Snapshot `job_items`, checkpoint pause/stop, retry phần lỗi, bảo vệ nhãn người/gốc, JSON proposals |
| `backend/dataset/operations.py` | Import ảnh/YOLO/YAML, dedup, backup clear, lựa chọn dữ liệu đủ điều kiện export |
| `backend/dataset/exports.py` | Snapshot tên duy nhất, nhóm camera/ngày/hash, chống trùng SHA giữa split, ZIP registry |
| `backend/detection/models.py` | YOLO + thiết bị/fallback; DINO và SAM tùy chọn |
| `backend/consensus/engine.py` | Ghép IoU một-một, giữ evidence/conflict, loại geometry lỗi; không giả xác suất đúng |
| `backend/traffic/analysis.py` | ROI/calibration, đếm xe/proxy, giữ nhãn người, stale features, classification và CSV |
| `frontend/app.js` | Điều hướng, dashboard, cấu hình, task/job, thư viện và export |
| `frontend/editor.js` | Canvas, review, undo/redo, dirty state, hàng chờ, phiên bản |
| `frontend/traffic.js` | Vẽ ROI, ngưỡng camera, duyệt classification |
| `frontend/api.js`, `theme.js` | API/error/dialog/toast, utility, theme |

## Trạng thái và tính nhất quán

`images.status` mô tả xử lý (`pending/processing/processed/failed`). `review_state` độc lập (`unreviewed/reviewed/negative`), cùng `review_version` tăng khi inference/review thay đổi ảnh. PUT review dùng compare-and-swap trong transaction: sai version trả 409, mọi validation lỗi rollback. ID ảnh tiếp tục tăng sau clear để tab cũ không ghi vào dataset mới. Annotation giữ metadata nguồn; lịch sử ghi create/update/delete/review.

Job gồm tổng cố định từ `job_items`. `processed + failed ≤ total`; retry chỉ đưa failed/processing về pending. Pause và stop ở ranh giới ảnh; restart đưa processing về pending, running về paused. Cancel giữ các kết quả đã commit nhưng không resume cùng job. Nhãn manual/original/ảnh đã duyệt được bảo vệ khỏi chạy lại.

`JobRunner.lock` phối hợp các mutation trong process. TaskManager bật maintenance trước import/clear/export/analyze/model-check; endpoint review/ROI không ghi trong thời gian này. Worker bật maintenance khi phân tích traffic hậu kỳ. Không dùng nhiều process cho cùng workspace. SQLite foreign keys và WAL hỗ trợ đọc trong lúc xử lý, không thay thế khóa nghiệp vụ.

## Quality và provenance

`high_agreement`, `needs_review`, `high_risk` là tier heuristic, không phải độ tin cậy đã hiệu chuẩn. AI acceptance mặc định tắt. Lưu review gắn `human_reviewed`/`human_rejected` cho box; chỉ complete review mới đánh dấu ảnh đã duyệt. Không export một phần proposal hoặc nhãn nhập lỗi thành ground truth thiếu box.

Traffic đếm theo tâm box nằm trong ROI đường, bỏ vùng exclusion và box human-rejected. Tổng diện tích box/diện tích ROI là **proxy**, có thể chồng lấn, không phải mask union. Calibration sinh gợi ý theo luật. Human-verified label/provenance được giữ qua phân tích lại; ROI/review đánh dấu features stale. CSV không tạo timestamp/nội suy giả và không cắt hàng theo phân trang UI.

## I/O và giới hạn hiệu năng

Ảnh nguồn không copy vào workspace khi import; SQLite giữ đường dẫn tuyệt đối, hash, kích thước. Thumbnail được cache 320×200, replace nguyên tử. Import quét một lần và commit từng 25 file. Export tạo thư mục riêng, validation nguồn/nhãn, copy ảnh, ghi manifest rồi ZIP; registry chỉ được ghi sau khi ZIP thành công.

Phân trang giúp UI không dựng toàn bộ dataset. Import danh sách file/hash, split/export candidates, manifest và temporal CSV vẫn cần bộ nhớ theo kích thước dataset; chưa phải streaming hoàn toàn. ZIP dùng thêm dung lượng và CPU, không có nút hủy maintenance. Snapshot đã export không bị clear workspace xóa; backup DB không bao gồm ảnh nguồn. Không có authentication, cơ chế nhiều project, task queue phân tán hoặc benchmark production trong bản này.
