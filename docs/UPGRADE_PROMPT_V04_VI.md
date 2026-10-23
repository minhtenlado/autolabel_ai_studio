# Form thực thi nâng cấp AutoLabel AI Studio 0.4

Bạn là kỹ sư phụ trách nâng cấp trực tiếp repository `minhtenlado/autolabel_ai_studio` từ commit `0c9400a`. Đọc mã hiện có, giữ FastAPI + SQLite + JavaScript chạy cục bộ, hỗ trợ chế độ web không cần PyTorch. Triển khai thật, không thay bằng demo, không tự bịa kết quả AI hoặc benchmark.

## Mục tiêu và thứ tự ưu tiên

1. **Bảo toàn dữ liệu.** Migration bổ sung cột/bảng và sao lưu database cũ; import không xóa dataset trước khi kiểm tra thư mục. Chặn xung đột với job đang chạy. Nhận diện cấu trúc YOLO lồng nhau; kiểm tra đầy đủ ảnh/nhãn, không bỏ qua label lỗi một cách im lặng.
2. **Review đáng tin cậy.** Phân biệt xử lý AI với duyệt ảnh; lưu phiên bản ảnh để phát hiện hai tab ghi đè. Giữ metadata YOLO/DINO/SAM. Hỗ trợ ảnh âm tính do người dùng xác nhận; bảo vệ sửa đổi chưa lưu; undo/redo đầy đủ và vẽ box mọi hướng.
3. **Job có thể tiếp tục.** Chụp danh sách ảnh của mỗi job, duy trì tiến độ nhất quán qua stop/resume/restart. Stop/cancel giữ kết quả đã commit, phản ánh trạng thái trung gian chính xác. Không nhân đôi nhãn gốc hoặc nhãn đã duyệt.
4. **Import và tác vụ dài.** Chạy nền với tiến độ thực, giao diện vẫn dùng được; thông báo lỗi có hành động khắc phục. Thumbnail nhẹ, phân trang và tìm kiếm có debounce, không tải toàn bộ 39.000 ảnh vào DOM.
5. **Traffic và classification.** Giữ nhãn human-verified nhất quán trong DB, JSON và CSV khi phân tích lại. Loại annotation đã bị người dùng bác bỏ; hỗ trợ ROI exclusion. Không cắt ngầm dữ liệu xuất ở 2.000 hàng. ROI có thể vẽ trên ảnh và hiệu chuẩn bằng các trường nhập dễ hiểu; nhãn theo luật phải được ghi rõ là gợi ý.
6. **Export.** Snapshot mới không ghi đè, chỉ xuất dữ liệu đủ điều kiện; không biến ảnh chưa duyệt thành negative. Split theo camera/ngày khi có timestamp, cảnh báo nhóm thiếu dữ liệu validation; manifest truy xuất được nguồn và chính sách duyệt. Có lịch sử và tải ZIP. Classification mặc định chỉ dùng nhãn người đã duyệt.
7. **Giao diện.** Thiết kế lại tiếng Việt, chữ đọc được, điều hướng đầy đủ trên điện thoại, sáng/tối, quy trình Nhập ảnh → Gán nhãn AI → Kiểm duyệt → Xuất. Dashboard số thật, trạng thái rỗng hữu ích, thông báo kết quả rõ ràng, khóa nút đang xử lý, phím tắt chỉ hoạt động trong editor. Có bộ lọc cần duyệt/rủi ro cao, xem lỗi và nhật ký.
8. **Bàn giao.** Báo cáo kiểm tra mã, tài liệu sử dụng/giới hạn, changelog và test hồi quy. Chạy unit/API tests, kiểm tra JavaScript, smoke test trình duyệt desktop/mobile; ghi rõ checkpoint và GPU nào chưa được thử. Commit trên nhánh riêng; bàn giao nguồn có thể chạy và bản patch nếu chưa có quyền đẩy GitHub.

## Tiêu chí nghiệm thu

- Backend và giao diện khởi động được chỉ với requirements web.
- Import path sai không làm mất dữ liệu; input không hợp lệ trả 4xx có nội dung dễ hiểu.
- Hai review cùng phiên bản: lần ghi sau trả 409; metadata gốc không bị mất.
- Ảnh rỗng chỉ xuất làm negative khi được xác nhận; chưa duyệt không được giả làm ground truth.
- Phân tích traffic lại vẫn giữ nhãn con người, class ID và provenance khớp CSV.
- Pause/stop/resume không tăng progress quá 100%, không đổi stop thành cancel.
- Tác vụ dài báo tiến độ, nút điều khiển hợp lệ theo trạng thái, frontend không phát sinh lỗi console trong luồng kiểm thử.
- Không thêm backend cloud, không yêu cầu GPU để review, không tải weights lớn nếu người dùng chưa cung cấp.

Hãy tự đọc lại form này trước khi triển khai; ghi kết quả thực tế và phần còn giới hạn trong `docs/AUDIT_V04_VI.md`.
