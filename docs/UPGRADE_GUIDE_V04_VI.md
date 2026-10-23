# Nâng cấp AutoLabel AI Studio 0.3 → 0.4

## Máy đang có dữ liệu

1. Dùng **Dừng an toàn**, đợi worker kết thúc ảnh hiện tại rồi tắt server. Sao lưu nguyên `workspace/` và giữ thư mục `models/`; nếu dùng `AUTOLABEL_DATA_DIR`, sao lưu đúng thư mục đó.
2. Cập nhật mã từ nhánh nâng cấp hoặc giải nén gói source 0.4 vào thư mục riêng. Gói source không chứa dataset, weights hay môi trường Python của máy phát triển.
3. Nếu dùng thư mục source riêng trên cùng máy, đặt `AUTOLABEL_DATA_DIR` trỏ đến workspace cũ. Đường dẫn ảnh nguồn vẫn phải tồn tại. Cài lại requirements bằng Python của `.venv`: `python -m pip install -r requirements.txt`. Nếu tạo môi trường mới, chạy `python install.py --mode web` hoặc chế độ AI phù hợp.
4. Chạy launcher một process. Migration bổ sung cột/bảng, sao lưu DB cũ vào `workspace/backups/pre-v04-*.sqlite3`, không xóa ảnh/nhãn. Kiểm tra tổng ảnh, mở vài ảnh có nhãn, xem model path, ROI và chạy một export nhỏ trước khi tiếp tục công việc lớn.
5. Mở lại tab trình duyệt hoặc tải lại trang. `frontend/` hiện là source được phục vụ trực tiếp; không cần build/copy `frontend/dist`.

**Không chạy đồng thời 0.3 và 0.4 trên cùng workspace.** Muốn quay lại 0.3, tắt mọi server, giữ một bản sao workspace hiện tại, rồi khôi phục backup trước nâng cấp sang workspace riêng để chạy mã 0.3. Backup DB không bao gồm ảnh nguồn/masks; giữ bản sao workspace đầy đủ nếu cần rollback trọn vẹn. Nhãn đã chỉnh trong 0.4 sau backup sẽ không có trong bản rollback.

Dữ liệu legacy không được tự suy diễn là ảnh đã duyệt đầy đủ. Vì 0.3 không có trạng thái duyệt cấp ảnh, các ảnh này bắt đầu `unreviewed`; nhãn nhập hợp lệ vẫn có thể export với provenance `imported`, nhãn manual/AI cần xác nhận lại ảnh để đáp ứng chính sách export mới.

## Áp dụng bản patch

Patch đi kèm được tạo từ commit `0c9400ac9cf61de5b3bf5e6ce502015870c293f1` của repository gốc. Với một checkout sạch tại commit này:

```bash
git switch -c upgrade/studio-v04
git apply --check /path/to/autolabel-v04.patch
git apply /path/to/autolabel-v04.patch
```

Nếu checkout đã có thay đổi khác, đọc diff và xử lý xung đột trước; không ghi đè workspace hay thay đổi chưa commit. ZIP source đầy đủ là lựa chọn nếu không dùng Git. Bản bàn giao chưa tự push lên GitHub.

## Những thay đổi có thể ảnh hưởng tích hợp

| Mục | 0.4 |
|---|---|
| Review `PUT /api/images/{id}/review` hoặc `/annotations` | Cần `expected_version` lấy từ `GET /api/images/{id}`; `complete` để xác nhận ảnh, `negative` để xác nhận không có xe. Tab cũ trả 409, không ghi đè |
| Metadata | API trả object; không `JSON.parse()` thêm. Evidence cũ được giữ khi update |
| Import | `clear_first` kiểm tra trước khi xóa; `keep_duplicates` tùy chọn giữ frame trùng khác path. Lỗi nhãn được lưu sự kiện |
| Tác vụ dài | Thêm `background: true` cho import/export; nhận `task_id`, poll `/api/tasks/{id}`. Không truyền vẫn có chế độ đồng bộ |
| Traffic analyze | `POST /api/traffic/analyze?background=true`; cờ background là query parameter |
| Job | Thêm `job_items`; stop là `stopping` → `stopped`, cancel riêng. `analyze_traffic_after` mặc định true trong API |
| Review/export song song | Maintenance import/export/analyze chặn ghi review; inference chặn ảnh đang xử lý, ảnh khác có thể review trước giai đoạn traffic |
| Lưu incremental | JSON proposal + ảnh dưới `job_N/`, không còn `.txt` rỗng làm nhãn train |
| Output export | `output_dir` là thư mục cha; luôn tạo snapshot con duy nhất, không ghi đè |
| Detection export | Mặc định reviewed/negative hoặc nhãn gốc nhập hợp lệ. `include_pseudo` là opt-in; ảnh AI phải `processed`, có box và mọi box có lớp/geometry hợp lệ. Khi dừng job giữa chừng, ảnh pending không được xuất; toàn bộ box của ảnh hoàn tất được ghi provenance pseudo-label dù chưa auto-accept |
| Phân trang | `/api/images`: limit tối đa 200; `/api/traffic/labels`: tối đa 500. Export lấy toàn bộ dữ liệu đủ điều kiện |
| ZIP tải xuống | `/api/exports`, `/api/exports/{id}/download`; không mở đường dẫn file tùy ý qua endpoint download |
| Traffic CSV | Giữ nhãn human-verified; chặn nếu features stale; extended schema, không giả tương thích TCN legacy |
| Giao diện | Phục vụ trực tiếp `frontend/`, các module JS rõ trách nhiệm; bỏ bản dist trùng |

Ví dụ lưu review:

```json
{
  "expected_version": 3,
  "complete": true,
  "negative": false,
  "annotations": [
    {"id": 12, "class_name": "car", "box": [10, 20, 100, 150], "accepted": true}
  ]
}
```

`annotations` là toàn bộ danh sách muốn giữ; ID cũ không gửi lên sẽ được xóa và ghi lịch sử. Tọa độ nằm trong kích thước ảnh hiển thị. Khi có lỗi, transaction rollback toàn bộ thay vì lưu dở.

## Phần triển khai tiếp theo cần dữ liệu thực tế

- Đánh giá detector trên gold set theo từng camera/độ sáng/cỡ xe; đo recall, precision và thời gian thực trước khi thay model/preset mặc định.
- Hiệu chuẩn traffic với nhãn chuyên gia; định nghĩa schema, sampling, normalization và split cho TCN trước khi huấn luyện.
- Đo RAM/latency/import/export trên dataset lớn; cân nhắc streaming export và queue đa process sau benchmark.
- Nếu cần nhiều người dùng/public service: xác thực, phân quyền theo project, lưu trữ chia sẻ, queue backend và khóa phân tán; không bật nhiều worker với khóa trong process hiện tại.
