# AutoLabel AI Studio 0.4

Ứng dụng gán nhãn ảnh giao thông chạy cục bộ: **FastAPI + SQLite + giao diện tiếng Việt**. Quy trình Nhập ảnh → Gán nhãn AI → Kiểm duyệt → Xuất dataset. Giữ kiến trúc nhẹ, không cần Node/build frontend và không cần GPU để quản lý, sửa nhãn hoặc xuất dữ liệu.

**Bản 0.4 tập trung vào trải nghiệm sử dụng và tính đúng của dữ liệu.** Có editor mới, dark mode, điều hướng mobile, import nền, thumbnail, phát hiện tab review cũ, xác nhận negative, job tiếp tục được, ROI trực quan, export snapshot/ZIP và lịch sử. Không bao gồm trọng số `best.pt`; không tuyên bố tăng độ chính xác AI khi chưa đánh giá checkpoint trên tập chuẩn.

- [Form nâng cấp đã thực thi](docs/UPGRADE_PROMPT_V04_VI.md)
- [Phân tích mã, kết quả và giới hạn kiểm thử](docs/AUDIT_V04_VI.md)
- [Nâng cấp từ 0.3 và thay đổi API](docs/UPGRADE_GUIDE_V04_VI.md)
- [Kiến trúc](docs/architecture.md) · [Changelog](CHANGELOG.md)

## Cài và chạy

Dùng Python **3.11 hoặc 3.12**, 64-bit. Installer cho phép 3.10–3.13; khả năng cài AI còn phụ thuộc wheel/driver. Cần Internet lúc cài dependency hoặc tải model, sau đó ứng dụng dùng ảnh và checkpoint trên máy.

### Windows

```bat
setup.bat --mode web
run.bat
```

Nếu không có `py`: `python install.py --mode web`, rồi `.venv\Scripts\python.exe launch.py`.

### Linux / macOS

```bash
python3 install.py --mode web
.venv/bin/python launch.py
```

Mở **http://127.0.0.1:8000**. API docs: **http://127.0.0.1:8000/docs**. Dừng bằng Ctrl+C. Linux có thêm `./run.sh` / `./stop.sh` để chạy nền; dùng launcher foreground khi cần xem lỗi.

| Chế độ cài | Chức năng |
|---|---|
| `python install.py --mode web` | Quản lý ảnh, review, ROI, xuất dữ liệu; không cài Torch |
| `python install.py --mode cpu` | Thêm YOLO/Torch CPU |
| `python install.py --mode auto` | Chọn bản Torch theo môi trường; kiểm tra accelerator sau cài |
| `python install.py --mode gpu` | Cài Torch từ PyPI; cần driver tương thích |
| `python install.py --mode auto --optional` | Thêm dependency cho Grounding DINO / SAM |
| `python install.py --mode gpu --torch-index URL` | Chỉ định index PyTorch phù hợp CUDA/ROCm |

Có GPU vật lý không đảm bảo Torch dùng được GPU. `Auto` chọn accelerator khả dụng; YOLO có fallback CPU với các lỗi accelerator được nhận diện. Chạy `.venv/bin/python -m scripts.doctor` để xem tình trạng thực tế; Windows dùng `.venv\Scripts\python.exe`.

## Dùng theo từng bước

### 1. Nhập ảnh

Nhập đường dẫn thư mục **trên máy chạy backend**. Hỗ trợ JPG/JPEG/PNG/WebP/BMP, quét thư mục con, đọc cả cấu trúc `images/train/camera` → `labels/train/camera`. Nút **Thay thế dataset** cần xác nhận; đường dẫn sai, không có ảnh đọc được hoặc YAML lỗi không xóa dữ liệu cũ. DB được sao lưu trước thay thế.

- Kiểm tra ảnh đầy đủ, SHA-256 và từng dòng nhãn YOLO detection 5 cột. Lỗi hiện trong Nhật ký; ảnh có nhãn lỗi cần review trước export.
- Nếu có `data.yaml` / `dataset.yaml` / `data.yml` ở thư mục nhập hoặc tổ tiên gần nhất, đọc trường `names` và đổi ID sang schema `bus, car, container, motorcycle, truck`. Class ngoài schema được báo lỗi, không đổi ngầm. Nếu không có YAML thì dùng đúng thứ tự 5 lớp này.
- Mặc định bỏ ảnh trùng nội dung. Bật **Giữ ảnh trùng nội dung** cho chuỗi traffic cần frame ở nhiều thời điểm; cùng đường dẫn không được nhập hai lần.
- Camera lấy từ thư mục con đầu tiên, bỏ các cấp `images/train/val/valid/test`. Timestamp đọc từ tên dạng `YYYYMMDD_HHMMSS`, `YYYYMMDD-HHMMSS` hoặc `YYYYMMDDTHHMMSS`; thiếu thì giữ rỗng, không tự bịa thời gian.
- Ảnh có EXIF orientation được hiển thị/xuất theo cùng hướng chuẩn hóa. Nhãn nhập cần tương ứng ảnh hiển thị. Một YAML được áp dụng cho toàn bộ lượt nhập; tách lượt nhập nếu nhiều dataset có schema khác nhau.
- Nhãn `.txt` rỗng chưa phải negative đã kiểm chứng. File nguồn luôn được giữ nguyên.

Import chạy nền và báo số ảnh quét/thêm/trùng/lỗi. Giao diện phân trang 48 ảnh, thumbnail nhẹ, tìm kiếm có debounce và bộ lọc trạng thái/rủi ro/lỗi.

### 2. Gán nhãn AI

Đặt checkpoint **YOLO detection** tại `models/best.pt`, hoặc chọn đường dẫn của bạn. Model phải có các tên class `bus`, `car`, `container`, `motorcycle`, `truck`; checkpoint classification/segmentation không được dùng thay detection.

Chọn thiết bị và preset: CPU fast (640), Standard (960), Small object (tiles), High accuracy (1280). Kiểm tra model trước khi chạy. DINO/SAM là tùy chọn; tải weights hợp lệ bằng `scripts/download_models.py` sau khi cài dependency tùy chọn. Bản nguồn chỉ có `models/README.txt`, không kèm weights.

Mặc định proposal cần review. Auto-accept YOLO + DINO đồng thuận hoặc YOLO-only là **opt-in pseudo-label**, không trở thành ground truth chỉ vì score cao. SAM gợi ý hình học, không xác nhận đúng lớp.

Job lưu danh sách ảnh và commit sau từng ảnh. Tạm dừng/dừng/hủy có hiệu lực ở ranh giới ảnh, không ngắt inference đang chạy. **Dừng an toàn** cho phép tiếp tục cùng job; **Hủy job** kết thúc phần còn lại và giữ kết quả đã lưu. Resume chỉ chạy phần chưa hoàn tất/lỗi, không làm progress vượt 100%. Khi khởi động lại, job bị gián đoạn trở về trạng thái có thể tiếp tục. Muốn xuất phần đã gán nhãn giữa chừng: bấm **Dừng an toàn**, đợi job chuyển sang Đã dừng, vào Xuất dataset và bật tùy chọn pseudo-label. Snapshot chỉ lấy ảnh `processed`; ảnh pending không vào export. Ảnh đang inference được hoàn tất rồi mới dừng.

Nếu bật lưu proposal liên tục, thư mục `job_N/` chứa ảnh và **JSON**, không tạo nhãn YOLO rỗng cho ảnh chưa duyệt. Mặc định cập nhật đặc trưng traffic sau detection; có thể tắt trong tùy chọn nâng cao.

### 3. Kiểm duyệt

Mở ảnh từ thư viện/hàng chờ. Vẽ box mọi hướng, kéo hoặc thay đổi kích thước, sửa lớp và acceptance. Có lớp YOLO/DINO/SAM để đối chiếu, undo/redo, lịch sử, lưu bản đang sửa, lưu xác nhận và lưu & ảnh tiếp.

| Phím trong editor | Thao tác |
|---|---|
| B / V / F | Vẽ / chọn / fit ảnh |
| Space + kéo / cuộn | Pan / zoom |
| 1–5 | Đổi lớp box đang chọn |
| Delete / Backspace | Xóa box chọn |
| Ctrl/Cmd+Z; Ctrl/Cmd+Y hoặc Shift+Z | Undo; redo |
| Ctrl/Cmd+S | Lưu và xác nhận ảnh |
| ← / → | Ảnh trước / tiếp |

Rời ảnh có sửa đổi sẽ hỏi giữ hay bỏ; chọn bỏ khôi phục trạng thái đã lưu. Muốn xác nhận negative, loại tất cả box accepted rồi bật **Tôi xác nhận ảnh không có xe**. Hai tab cùng sửa một ảnh: tab cũ nhận 409 và giữ chỉnh sửa cục bộ, để người dùng tải lại/quyết định; không ghi đè ngầm. Metadata model được giữ khi sửa.

### 4. Traffic & ROI

Chọn camera, vẽ vùng đường/vùng loại trừ trên ảnh, đặt `free_max ≤ busy_max < jam_min`, rồi xác nhận hiệu chuẩn theo dữ liệu camera. Có JSON nâng cao cho cấu hình đã có. Chạy phân tích nền, xem các gợi ý và xác nhận/loại nhãn classification.

Nhãn theo ngưỡng là **gợi ý theo luật**, chưa phải mô hình classifier đã huấn luyện. Box đã bị người duyệt bác bỏ không được đếm. Nhãn người xác nhận được giữ nhất quán khi phân tích lại. Review detection hoặc đổi ROI đánh dấu đặc trưng cũ; phải phân tích lại trước khi xuất CSV.

### 5. Xuất dataset

| Kiểu | Nội dung / chính sách mặc định |
|---|---|
| YOLO Detection | Mặc định lấy ảnh đã duyệt đầy đủ (kể cả negative) hoặc ảnh có nhãn nhập hợp lệ. Tùy chọn pseudo-label lấy toàn bộ box AI trên từng ảnh `processed`, kể cả box chưa chấp nhận; ảnh pending, ảnh không có box và ảnh có box/lớp không hợp lệ bị loại |
| Classification | Chỉ nhãn người đã xác nhận. Pseudo-label theo luật cần bật riêng |
| Traffic CSV | Toàn bộ bản ghi có timestamp, không giới hạn ngầm 2.000 hàng; giữ provenance/trạng thái review và báo số bỏ qua |

Mỗi lần xuất tạo **thư mục riêng + ZIP + manifest + lịch sử**, không ghi đè bản cũ. Thư mục tùy chọn là thư mục cha, snapshot được tạo bên trong. Chuẩn bị dung lượng cho cả ảnh copy và ZIP. Nhãn AI xuất theo tùy chọn vẫn là pseudo-label, chưa phải ground truth; dự đoán rỗng không được hiểu là ảnh nền nếu chưa có người xác nhận.

Detection/classification mặc định chia nhóm camera/ngày; các nhóm có ảnh trùng SHA-256 được gộp để tránh trùng nội dung train/val. Thiếu timestamp sẽ fallback hash và cảnh báo. Chỉ một nhóm thì toàn bộ vào train, val rỗng có cảnh báo. Tỷ lệ val là tỷ lệ **nhóm**, không đảm bảo đúng tỷ lệ số ảnh hay cân bằng class. Cách chia này chưa loại trừ mọi dạng rò rỉ dữ liệu.

## Cấu hình và chạy từ xa

Server mặc định bind loopback; **một process / một workspace**. Không dùng nhiều Uvicorn workers cùng DB vì khóa điều phối nằm trong process. API chưa có đăng nhập/phân quyền nên phù hợp máy cá nhân hoặc môi trường riêng.

| Biến môi trường | Ý nghĩa |
|---|---|
| `AUTOLABEL_DATA_DIR` | Thư mục SQLite, masks, thumbnails, backups, exports |
| `AUTOLABEL_YOLO_MODEL` | Đường dẫn checkpoint mặc định |
| `AUTOLABEL_DEVICE` | Thiết bị mặc định; lựa chọn UI theo job ưu tiên hơn |
| `AUTOLABEL_CPU_THREADS` | Số luồng Torch CPU |
| `AUTOLABEL_PORT` | Port, mặc định 8000 |
| `AUTOLABEL_HOST` | Host, mặc định 127.0.0.1 |

Truy cập máy khác qua SSH tunnel: `ssh -L 8000:127.0.0.1:8000 user@HOST`, sau đó mở localhost. Bind ngoài loopback cần opt-in `AUTOLABEL_INSECURE_REMOTE=1` và lớp bảo vệ phù hợp.

Docker CPU (chưa chạy kiểm thử Docker trong đợt nâng cấp này):

```bash
docker build -t autolabel-studio:cpu .
docker run --rm -p 127.0.0.1:8000:8000 -v "$PWD/workspace:/app/workspace" -v "$PWD/models:/app/models:ro" -v "$PWD/dataset:/data:ro" autolabel-studio:cpu
```

Nhập `/data` ở giao diện container. Model/database không nhúng vào image.

## Kiểm thử và giới hạn

```bash
# Python của .venv; Windows thay bằng .venv\Scripts\python.exe
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q backend tests
```

47 unit/API/worker regression tests đã đạt trên Linux/Python 3.12.14; tests dùng DB và ảnh tạm riêng. Bao gồm migration, bad import giữ dữ liệu, class mapping, stale tab, review atomic, negative, split, 2.006 bản ghi CSV, human provenance, stop/pause/resume/restart. Worker tests dùng detector giả lập, không đo chất lượng AI.

Browser test tùy chọn cần Node + Playwright/Chromium (không cần cho người dùng ứng dụng):

```bash
npm install --no-save --package-lock=false playwright
npx playwright install chromium
PYTHON="$PWD/.venv/bin/python" node tests/ui_smoke.mjs
```

Có thể đặt `PLAYWRIGHT_MODULE` (đường dẫn `index.mjs`), `CHROMIUM_EXECUTABLE`, `UI_TEST_PORT`, `UI_SCREENSHOT_DIR`. Test tự chạy server/DB tạm và fixture ghi rõ SYNTHETIC; không sử dụng workspace thật. Trên PowerShell đặt `$env:PYTHON` trước khi chạy Node.

**Chưa xác minh:** `best.pt` thật của người dùng, inference DINO/SAM thật, CUDA/ROCm/MPS, Windows/macOS/Docker thực tế, tải hàng chục nghìn ảnh và throughput. Chưa có benchmark chứng minh tăng độ chính xác hoặc tốc độ AI. CPU/GPU vẫn phụ thuộc model, driver và bộ nhớ.

SQLite lưu đường dẫn tuyệt đối; chuyển máy cần giữ mount/đường dẫn tương ứng hoặc import lại ảnh. Không thay file ảnh nguồn sau khi import: SHA/kích thước và nhãn sẽ không tự cập nhật. Import bị ngắt giữ các batch đã commit; chạy lại cùng thư mục để nhập tiếp. Traffic occupancy chỉ là proxy từ bounding box, không phải hợp vùng mask; CSV chưa resample và chưa tương thích TCN 720/180 được kiểm chứng.
