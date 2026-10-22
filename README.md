# AutoLabel AI Studio 0.3 – chạy trên CPU hoặc GPU

Ứng dụng gán nhãn ảnh giao thông local-first (FastAPI + SQLite + giao diện trình duyệt): YOLO detection, tùy chọn Grounding DINO để đối chiếu và SAM để gợi ý mask/box. Có import ảnh, rà soát thủ công, xuất YOLO Detection và trạng thái giao thông/Classification đã kiểm chứng. **Không cần GPU để mở giao diện; để tự động nhận diện phải cài PyTorch, Ultralytics và cung cấp trọng số YOLO phù hợp.**

## 1. Cài đặt sạch trên máy mới

**Khuyến nghị:** Python **3.11 hoặc 3.12** (hỗ trợ 3.10–3.13 theo bản wheel của thư viện), kết nối Internet lúc cài đặt và tải trọng số. Dùng bản Python 64-bit trên Windows/macOS/Linux. RAM tối thiểu thực tế phụ thuộc kích thước checkpoint; để chạy DINO/SAM cùng YOLO cần nhiều RAM hơn đáng kể.

### Windows (PowerShell / CMD)

Mở thư mục ZIP đã giải nén, chạy:

```bat
setup.bat --mode auto
run.bat
```

Nếu không có `py`, dùng `python install.py --mode auto` rồi `.venv\Scripts\python.exe launch.py`.

### Linux / Ubuntu

```bash
cd autolabel_ai_studio
chmod +x setup.sh run.sh stop.sh
./setup.sh --mode auto
./run.sh
```

Hoặc chạy foreground (hiện lỗi trực tiếp): `./.venv/bin/python launch.py`. Nếu thiếu venv trên Ubuntu: `sudo apt install python3-venv`.

### macOS (Intel / Apple Silicon)

```bash
python3 install.py --mode auto
.venv/bin/python launch.py
```

Trình duyệt truy cập **http://127.0.0.1:8000**. API docs: **http://127.0.0.1:8000/docs**. Để dừng: `Ctrl+C` khi chạy foreground; Linux `./stop.sh` nếu chạy nền. Windows đóng cửa sổ `run.bat` hoặc Ctrl+C.

### Các chế độ cài đặt

| Lệnh | Tính năng | Khi nào sử dụng |
|---|---|---|
| `python install.py --mode web` | FastAPI/UI/nhãn thủ công/export, không cài Torch | Máy yếu, chỉ rà soát ảnh |
| `python install.py --mode cpu` | YOLO bằng CPU, Torch CPU trên Windows/Linux | Máy không GPU hoặc driver không tương thích |
| `python install.py --mode auto` | GPU NVIDIA nếu thấy `nvidia-smi`, ngược lại CPU; Apple MPS nếu torch hỗ trợ | Lựa chọn mặc định |
| `python install.py --mode gpu` | Dùng bản PyTorch từ PyPI, kiểm tra CUDA sau khi cài | Máy GPU đã có driver phù hợp |
| `python install.py --mode auto --optional` | Thêm Transformers + thư viện DINO/SAM | Máy đủ RAM, muốn kiểm tra chéo |
| `python install.py --mode gpu --torch-index URL` | Tự chọn index PyTorch tương thích driver CUDA/ROCm | NVIDIA driver cụ thể hoặc AMD ROCm |

**Quan trọng:** có GPU vật lý không có nghĩa PyTorch sử dụng được GPU đó. AMD ROCm chỉ hoạt động trên hệ điều hành/card được bản torch ROCm hỗ trợ; Apple Silicon dùng MPS khi tương thích. Không thể đảm bảo chạy AI trên **mọi** CPU/OS/kiến trúc, ví dụ máy 32-bit hoặc Python không có wheel. Chạy `python -m scripts.doctor` bằng Python của `.venv` để xem chính xác tình trạng thiết bị; nếu GPU driver bị lỗi trong lúc suy luận và device là `auto`, YOLO sẽ thử lại trên CPU.

## 2. Mô hình và dữ liệu cần cung cấp

1. Đặt checkpoint YOLO detection huấn luyện của bạn tại **`models/best.pt`** (hoặc nhập đường dẫn đầy đủ trên **máy đang chạy server**). Tên class trong checkpoint phải khớp: `bus`, `car`, `container`, `motorcycle`, `truck`. ZIP này **không** bao gồm best.pt.
2. Không bắt buộc phải có DINO/SAM. Với máy CPU, hãy bắt đầu chỉ dùng YOLO (để trống 2 trường tùy chọn) và chế độ **CPU fast (640 px)** hoặc Standard (960 px), sau đó tăng dần nếu bỏ sót xe nhỏ.
3. Nếu muốn Grounding DINO / SAM, cài `--optional` rồi dùng `./.venv/bin/python scripts/download_models.py` (Linux/macOS), hoặc `.venv\Scripts\python.exe scripts\download_models.py` (Windows). Mạng được sử dụng **chỉ** để cài package / tải weights khi bạn chạy các lệnh này; inference cục bộ sau đó.
4. **Các file model.safetensors trong ZIP nguồn bị cắt cụt còn 2 MiB mỗi file**, không phải trọng số hợp lệ. Chúng đã được **loại khỏi bản này**, không sử dụng, không giả làm inference. Script tải model có kiểm tra cấu trúc/độ dài tensor khi tải xong. Trọng số chính thức có thể tổng cộng trên 1 GiB.
5. Ở mục `Dataset` nhập thư mục chứa ảnh nằm **trên chính máy chạy backend**, không phải đường dẫn máy đang mở trình duyệt từ xa. Các thư mục `images/` và `labels/` YOLO hiện có được tự nhận diện.

## 3. Workflow

- **Import**: JPG/JPEG/PNG/WebP/BMP theo thư mục; loại trùng hash SHA-256, không đổi file nguồn. Camera ID từ thư mục cha; timestamp được suy ra từ tên file theo dạng `YYYYMMDD_HHMMSS` nếu có.
- **Model check**: lựa chọn `Auto`, `CPU`, `CUDA/ROCm` hoặc `MPS`. Auto ưu tiên accelerator khả dụng theo torch; nếu không có sẽ chạy CPU. Nếu ép CUDA/MPS không khả dụng, trả lỗi rõ ràng.
- **Auto label**: chạy YOLO; DINO/SAM tùy chọn. YOLO-only thường được gắn `needs_review`, không tự nhận là nhãn chuẩn.
- **Acceptance**: mặc định `auto_accept` tắt. `Auto-accept high agreement` chỉ nhận detection đồng thuận đạt điều kiện; KHÔNG tự động chấp nhận nhãn mâu thuẫn/high risk. Có thêm checkbox **YOLO-only unverified** nếu chủ động chấp nhận rủi ro của nhãn một mô hình, không nên bật để tạo ground truth khoa học.
- **Review**: mở ảnh, thao tác box, phím 1–5 để gán lớp, Delete, Ctrl+Z/Y, kéo pan, scroll zoom, Ctrl+S lưu review vào SQLite với lịch sử sửa đổi.
- **Save while running** (`output_dir`): tên file thêm ID ảnh tránh hai camera trùng tên. Chỉ ghi **nhãn accepted** vào `.txt`; nếu chưa duyệt thì file nhãn rỗng. Đây là thư mục kết quả trung gian, không phải gold set.
- **Export**: xuất snapshot `workspace/exports/`, tạo `images/{train,val}`, `labels/{train,val}`, `data.yaml`, `manifest.json`, chỉ xuất accepted=1. Các trường hợp trạng thái giao thông/calibration đều là gợi ý cần review.

## 4. Chạy từ xa / cấu hình

Server mặc định chỉ bind **127.0.0.1** để tránh API ghi/xóa dữ liệu không xác thực bị lộ ra LAN/WAN. Trên máy khác, kết nối **SSH tunnel** đến máy chạy app:

```bash
ssh -L 8000:127.0.0.1:8000 user@YOUR_HOST
```

Rồi truy cập `http://127.0.0.1:8000`. Không public port 8000 lên Internet.

Biến môi trường:

- `AUTOLABEL_DATA_DIR`: đổi nơi lưu SQLite, masks, exports và lịch sử.
- `AUTOLABEL_YOLO_MODEL`: checkpoint YOLO mặc định.
- `AUTOLABEL_DEVICE=auto|cpu|cuda|mps`: device mặc định; chọn riêng trong UI ưu tiên hơn biến môi trường.
- `AUTOLABEL_CPU_THREADS`: đặt số luồng CPU cho Torch (mặc định số CPU - 1, tối đa 8).
- `AUTOLABEL_PORT`: port backend (mặc định 8000).
- `AUTOLABEL_HOST`: mặc định loopback. Nếu cần bind rộng phải **tự bật** `AUTOLABEL_INSECURE_REMOTE=1` và đặt reverse proxy/VPN/auth phù hợp; không khuyến nghị.

### Docker CPU (chỉ khi muốn container)

```bash
docker build -t autolabel-studio:cpu .
docker run --rm -p 127.0.0.1:8000:8000 -v "$PWD/workspace:/app/workspace" -v "$PWD/models:/app/models:ro" -v "$PWD/dataset:/data:ro" autolabel-studio:cpu
```

Trong giao diện container, nhập đường dẫn dataset **`/data`**. **Không** publish Docker port đến `0.0.0.0`; container bind all interfaces *bên trong* để Docker host-loopback forwarding hoạt động. Models và database **không** được tích hợp cố định vào image.

## 5. Kiểm tra

```bash
# Dùng .venv/bin/python ở Linux/macOS, .venv\Scripts\python.exe ở Windows
python -m scripts.doctor
python -m unittest discover -s tests -v
python -m compileall -q backend
```

Kiểm thử tự động gồm chọn device, lỗi GPU giả lập → CPU fallback, nhất quán API lưu review, gán nhãn/traffic logic. **Chưa có smoke test với checkpoint YOLO thật của người dùng**, nên không thể tuyên bố inference thực tế hoặc số ảnh/giây trên máy bạn được xác nhận. Chạy demo với ít ảnh và checkpoint hợp lệ trước khi dùng dataset lớn.

## 6. Giới hạn của bài toán

- DINO/SAM nặng trên CPU và có thể thiếu RAM. Không thể tăng tốc GPU nếu không có driver / torch wheel / GPU tương thích. `Auto` không tạo ra hiệu năng GPU trên máy chỉ có CPU.
- Sai khác kiến trúc YOLO/Transformers và model checkpoint ảnh hưởng kết quả; auto label chỉ là pseudo-label, cần kiểm chứng chất lượng trên gold set.
- Traffic pseudo-label theo threshold camera không phải ground truth; box occupancy là proxy, không phải mask-union occupancy. Chưa có learned classifier đã hiệu chuẩn, temporal resampling hoặc TCN 720/180 như mục tiêu hệ thống lớn.
- SQLite lưu đường dẫn tuyệt đối tới ảnh nguồn. Nếu **chuyển máy**, hãy **import lại folder ảnh** hoặc dùng cùng đường dẫn/mount. Đừng copy mỗi DB rồi kỳ vọng nó tự tìm thấy ảnh trên máy mới.
- Ứng dụng là local/private: API **chưa có xác thực người dùng**, không phù hợp triển khai public Internet nếu không có lớp xác thực/proxy.
