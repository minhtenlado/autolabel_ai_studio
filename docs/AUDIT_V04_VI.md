# Phân tích AutoLabel AI Studio và kế hoạch 0.4

Nguồn: nhánh main, commit `0c9400ac9cf61de5b3bf5e6ce502015870c293f1`. Đánh giá dựa trên đọc trực tiếp mã và 12 unit test gốc (đều pass), không suy diễn rằng các test này xác minh mô hình thật.

## Những gì đang có

Ứng dụng local-first gọn: FastAPI, SQLite WAL, worker thread, YOLO detection, DINO đối chiếu tùy chọn, SAM đề xuất hình học, canvas review, ROI và classification bằng luật. CPU/GPU/MPS có cơ chế lựa chọn và fallback. Đây là nền tảng hợp lý, chưa cần chuyển framework hay thêm cloud.

## Lỗi và hạn chế xác nhận trong mã 0.3

| Mức | Vị trí | Phát hiện và ảnh hưởng |
|---|---|---|
| Cao | dataset/operations.py: import_folder | `clear_first` xóa trước khi xác minh folder; đường dẫn sai có thể xóa toàn bộ nhãn cũ. |
| Cao | api/app.py + pipeline/worker.py | Import không được khóa cùng worker; `clear_first` đi vòng qua kiểm tra ở endpoint clear. |
| Cao | frontend/app.js: openImage | API trả metadata dạng object nhưng UI lại JSON.parse object; metadata bị thay bằng `{}`, mất bằng chứng DINO/SAM khi lưu. |
| Cao | api/app.py: image_save_annotations | Không kiểm tra phiên bản review; tab cũ có thể ghi đè tab mới. Không có trạng thái xác nhận ảnh âm tính. |
| Cao | traffic/analysis.py: set_label, analyze_all | Nhãn được sửa không cập nhật class/id trong features JSON; analyze lại ghi đè provenance human_verified; CSV có thể xuất nhãn cũ. |
| Cao | traffic/analysis.py: temporal_records | Chỉ lấy tối đa 2.000 hàng qua list_labels, cắt ngầm CSV dataset lớn. |
| Cao | dataset/operations.py: export_dataset | Bỏ ảnh negative; xuất một phần box accepted trên ảnh còn proposal chưa duyệt; custom output có thể trộn/ghi đè export cũ. |
| Cao | pipeline/worker.py | Auto-save ghi `.txt` rỗng cho ảnh chưa chấp nhận, dễ bị hiểu thành nhãn negative khi train; `train` và `val` trùng thư mục. |
| Vừa | pipeline/worker.py | Resume thay total bằng số còn lại nhưng giữ processed; stop cuối vòng bị ghi thành cancelled; không có snapshot job items. |
| Vừa | dataset/operations.py | Đọc header ảnh chưa xác minh byte ảnh đầy đủ; đọc nhãn chưa hỗ trợ đúng images/train/subdir → labels/train/subdir. |
| Vừa | traffic/analysis.py | Đếm cả nhãn đã bị người dùng reject, chưa dùng exclusion; số chất lượng là heuristic chưa được hiệu chuẩn. |
| Vừa | frontend | 8–11 px phổ biến; CSS mobile giấu các mục điều hướng không active; thao tác clear/cancel bị định nghĩa nhiều lần; checkbox clearFirst không gửi API. |
| Vừa | frontend | Không có dirty guard, tìm kiếm không debounce, ảnh thu nhỏ tải file gốc, phím tắt áp dụng ngoài editor, undo thiếu thao tác acceptance. |
| Vừa | api/app.py | Route `/jobs/{action}` che `/jobs/resume`; model check giữ thêm checkpoint ngoài worker, có thể tăng bộ nhớ không cần thiết. |
| Thấp | frontend/dist | Hai bản source/dist thủ công dễ lệch; module mã nén dài khó bảo trì. |
| Cao | dataset/operations.py | Mặc định tin numeric class ID, không đọc tên lớp trong data.yaml; dataset có thứ tự class khác có thể bị gán nhầm. |

## Quyết định thiết kế

- Giữ stack và class schema cũ; migration có backup. Nâng cấp theo form đi kèm.
- Mặc định detection export chỉ ảnh đã duyệt hoàn chỉnh, hoặc ảnh có nhãn nhập hợp lệ không kèm proposal chưa xử lý. Cho phép xuất pseudo-label phải opt-in rõ ràng.
- Các ảnh camera liên tiếp cần tách theo nhóm camera/ngày để giảm rò rỉ; phương pháp này không đảm bảo hết mọi loại leakage. Với một nhóm chỉ xuất train và cảnh báo, không lén chia frame cùng nhóm sang val.
- ROI/count-based classification vẫn là luật, không phải YOLO classification được huấn luyện. Không tuyên bố có TCN tương thích khi chưa có schema/normalizer đã xác minh.
- Không đổi sang React chỉ vì nâng cấp giao diện; giữ khả năng cài web gọn, chạy offline sau cài dependency.

## Kết quả triển khai và kiểm thử

Đã tự đọc lại `UPGRADE_PROMPT_V04_VI.md` và triển khai trên nhánh `upgrade/studio-v04`, giữ nguyên FastAPI + SQLite + JavaScript. Bản 0.4 là mã ứng dụng đầy đủ, không phải mockup. Không cần chuyển stack để giải quyết các lỗi được xác nhận ở trên.

| Hạng mục trong form | Kết quả thực hiện | Bằng chứng |
|---|---|---|
| Bảo toàn dữ liệu | Backup trước migration/clear; xác minh input trước thay thế; import nền được khóa với worker | Tests invalid folder/empty/corrupt/YAML, migration giữ ảnh/nhãn, mutation gate |
| Nhập dataset | Decode ảnh, nested YOLO, YAML names mapping, nhãn lỗi có nhật ký, giữ frame trùng theo opt-in | Tests truncated image, nested labels, reordered classes, duplicates |
| Review | Metadata nguyên vẹn, version 409, validation atomic, negative explicit, lịch sử | API tests và trình duyệt lưu/xung đột/tải lại |
| Editor/UI | Giao diện mới tiếng Việt, dark mode, 7 view mobile, grid/table, queue, canvas, dirty guard/undo/redo | 15 nhóm browser checks; đã xem trực quan desktop, mobile, dark và ROI |
| Job | job_items bền vững, pause/stop/cancel đúng, resume/retry/restart không nhân đôi kết quả | Worker tests có event gate, detector giả lập và trạng thái DB |
| Traffic | Bảo toàn human label/JSON/CSV, exclusion, bỏ rejected box, stale features, tự phân tích sau job | Tests manual preservation, rejected state, ROI validation, automatic pass |
| Export | Snapshot/ZIP/lịch sử, review policy, không partial pseudo, grouping/hash dedup, CSV đầy đủ | Negative ZIP, pseudo opt-in, no overwrite, split isolation, 2.006 hàng CSV |
| Bàn giao | Source, patch, README, changelog, audit và hướng dẫn cập nhật | Nhánh riêng; chưa push vào GitHub |

### Những lỗi phát hiện và sửa thêm trong quá trình kiểm thử

- **ID ảnh tái sử dụng sau clear:** có thể khiến tab cũ gán nhãn nhầm ảnh mới. Lưu high-water ID và cấp ID tăng liên tục sau thay dataset; test tab cũ nhận 404.
- **Frame trùng ở nhiều camera/ngày:** giữ frame cho temporal có thể làm trùng nội dung train/val. Gộp các nhóm có SHA-256 chung trước split; có test nối nhóm qua cùng nội dung.
- **“Bỏ thay đổi” chưa khôi phục editor:** sửa để trả về snapshot đã lưu, dọn undo/redo; browser test kiểm tra sau điều hướng trở lại.
- **Sửa khi ảnh đang tải:** khóa input nhãn trong lúc tải/lưu để thao tác không bị kết quả đến sau thay thế ngầm.
- **Cập nhật traffic sau detection:** giữ maintenance gate trong giai đoạn này và cho phép resume phần traffic ngay cả khi inference đã đủ ảnh.
- **Tab mới/worker cập nhật:** UI hiển thị version mới sau lưu, xử lý 409 giữ bản đang sửa và có đường tải lại.

### Phạm vi xác minh thực tế

- Baseline: 12 unit test gốc pass trước thay đổi.
- Bản nâng cấp: **47 unit/API/worker tests pass**, Linux, Python **3.12.14**, chế độ web. Các test khởi tạo DB/ảnh riêng, không đụng workspace thật. Detector và lỗi GPU trong test được giả lập.
- Browser: Chromium **153.0.8010.0**, viewport **1440×1050** và **390×844**, fixture 12 ảnh có ghi rõ SYNTHETIC, một file ảnh hỏng và một bản trùng. **15 nhóm kiểm tra pass**: dashboard rỗng, import nền, search, nhãn gốc, vẽ ngược/undo/redo, dirty guard, lưu review, conflict hai tab, discard, ZIP detection, ROI/calibration/analyze, classification export, theme reload, 7 view mobile, không có lỗi JavaScript ngoài phản hồi 409 cố ý kiểm thử.
- Đã kiểm tra cú pháp Python/JS và diff whitespace. Mã mới được format để dễ review; không thêm framework frontend hoặc runtime cloud.
- Bộ test CSV dùng **2.006 bản ghi**, xác nhận export không cắt theo limit của UI. Đây không phải benchmark hiệu năng dataset lớn.

### Giới hạn cần giữ đúng khi vận hành

1. **Chưa có `best.pt` của người dùng:** chưa đo độ chính xác, tốc độ YOLO, chất lượng DINO/SAM hay VRAM thực tế. Không thể kết luận model tốt hơn chỉ từ nâng cấp UI/backend.
2. **Chưa thử CUDA/ROCm/MPS và OS khác:** mã portable được giữ, nhưng chưa chứng nhận chạy thực tế Windows/macOS/Docker trong lần này.
3. **Local, một process:** API chưa có auth/role/project. Khóa trong process không phù hợp multi-worker hoặc triển khai public nhiều người dùng.
4. **Dataset lớn chưa benchmark:** UI có phân trang/thumbnail, song import danh sách/hash, export candidates/manifest và temporal_records vẫn dùng RAM theo số ảnh. ZIP tạo thêm bản dữ liệu; maintenance chưa có nút hủy.
5. **Quy tắc chất lượng:** nhãn nhập hợp lệ vẫn chỉ là nhãn nhập; AI/traffic pseudo-label vẫn cần đánh giá trên gold set. Các ảnh legacy không được tự suy diễn thành fully reviewed.
6. **ROI và thời gian:** occupancy là box-area proxy, ngưỡng camera cần hiệu chuẩn; timestamp lấy từ tên ảnh giữ thời gian nguồn, chưa resample, nội suy, timezone normalization hoặc TCN 720/180.
7. **Split:** camera/ngày và gộp trùng hash giảm một số leakage, chưa bảo đảm camera holdout, scene similarity hay cân bằng class. Dataset một nhóm có val rỗng và cảnh báo.
8. **File nguồn:** DB dùng path tuyệt đối; cần giữ vị trí/nội dung ảnh. Copy DB đơn lẻ không chuyển được dataset sang máy khác. Backup tự động là DB, không thay cho backup toàn bộ workspace/ảnh.

### Ưu tiên vòng nâng cấp kế tiếp

| Ưu tiên | Việc cần làm | Đầu vào để quyết định |
|---|---|---|
| P1 | Benchmark checkpoint theo camera, điều kiện sáng và cỡ xe; chọn preset từ số đo | best.pt, gold set và máy đích |
| P1 | Hiệu chuẩn traffic, định nghĩa sampling/normalizer/schema trước TCN | Chuỗi có timestamp, nhãn chuyên gia |
| P2 | Streaming export, tối ưu batch inference, hủy maintenance có rollback rõ ràng | Dataset lớn và profile RAM/latency |
| P2 | CI đa nền tảng và lock dependency theo cấu hình triển khai | Môi trường Windows/macOS/Linux thực tế |
| P3 | Nhiều project/người dùng, phân quyền, queue và storage dùng chung | Nhu cầu cộng tác, hạ tầng vận hành |

Những mục này là đề xuất tiếp theo, không được tính là chức năng đã triển khai trong 0.4.
