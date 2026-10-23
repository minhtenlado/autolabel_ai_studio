import {
  $,
  $$,
  api,
  esc,
  icon,
  number,
  basename,
  statusLabel,
  toast,
  empty,
  confirmAction,
} from "./api.js";
const names = ["Thong_thoang", "Dong_xe", "Un_u_nhe", "Un_tac_nang"];
const labels = ["Thông thoáng", "Đông xe", "Ùn ứ nhẹ", "Ùn tắc nặng"];
const reasons = {
  missing_confirmed_road_roi: "Thiếu ROI đường",
  missing_timestamp_image_only_mode: "Thiếu timestamp",
  missing_detection_annotations: "Thiếu nhãn detection",
  unreviewed_detection_proposals: "Có box chưa duyệt",
  uncertain_vehicle_count: "Có lớp xe chưa rõ",
  camera_thresholds_not_calibrated: "Chưa xác nhận hiệu chuẩn",
};
export function createTraffic({ runTask, onChanged }) {
  let cameras = [],
    camera = "",
    regions = [],
    points = [],
    drawing = false,
    bitmap = null,
    initial = "",
    offset = 0,
    total = 0,
    loadToken = 0,
    tableToken = 0;
  const canvas = $("#roiCanvas"),
    context = canvas.getContext("2d");
  let frame = { x: 0, y: 0, w: 0, h: 0 };
  function config() {
    const values = ["freeMax", "busyMax", "jamMin"].map(
      (id) => $("#" + id).value,
    );
    const calibration = values.every((v) => v === "")
      ? {}
      : {
          free_max: Number(values[0]),
          busy_max: Number(values[1]),
          jam_min: Number(values[2]),
        };
    return {
      rois: regions,
      calibration,
      calibration_confirmed: $("#calibrationConfirmed").checked,
    };
  }
  const dirty = () =>
    Boolean(camera && (JSON.stringify(config()) !== initial || points.length));
  async function canLeave() {
    if (!dirty()) return true;
    const discard = await confirmAction({
      title: "Cấu hình camera chưa lưu",
      body: "Vùng ROI hoặc ngưỡng đang chỉnh sẽ bị bỏ. Đóng hộp thoại để lưu trước khi rời trang.",
      confirmText: "Bỏ thay đổi",
      danger: true,
    });
    if (discard) applyConfig(JSON.parse(initial));
    return discard;
  }
  function renderRegions() {
    $("#roiRegions").innerHTML = regions.length
      ? regions
          .map(
            (r, i) =>
              `<span class="region-chip ${r.type === "exclusion" ? "exclusion" : ""}">${esc({ road: "Vùng đường", exclusion: "Loại trừ", lane: "Làn xe", queue: "Vùng hàng chờ" }[r.type])} ${i + 1} · ${r.polygon.length} điểm<button data-remove-roi="${i}" aria-label="Xóa vùng ${i + 1}">×</button></span>`,
          )
          .join("")
      : '<p class="hint">Chưa có vùng nào. Bấm Vẽ vùng mới để bắt đầu.</p>';
    $("#roiJson").value = JSON.stringify(config(), null, 2);
    draw();
  }
  function draw() {
    const rect = canvas.parentElement.getBoundingClientRect(),
      dpr = window.devicePixelRatio || 1;
    if (!rect.width || !rect.height) return;
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (!bitmap) return;
    const scale = Math.min(
      rect.width / bitmap.naturalWidth,
      rect.height / bitmap.naturalHeight,
    );
    frame = {
      w: bitmap.naturalWidth * scale,
      h: bitmap.naturalHeight * scale,
      x: (rect.width - bitmap.naturalWidth * scale) / 2,
      y: (rect.height - bitmap.naturalHeight * scale) / 2,
    };
    context.drawImage(bitmap, frame.x, frame.y, frame.w, frame.h);
    function polygon(poly, color, closed) {
      if (!poly.length) return;
      context.beginPath();
      poly.forEach(([x, y], i) =>
        context[i ? "lineTo" : "moveTo"](
          frame.x + x * frame.w,
          frame.y + y * frame.h,
        ),
      );
      if (closed) context.closePath();
      context.fillStyle = color + "35";
      if (closed) context.fill();
      context.strokeStyle = color;
      context.lineWidth = 2;
      context.stroke();
      poly.forEach(([x, y], i) => {
        context.beginPath();
        context.arc(
          frame.x + x * frame.w,
          frame.y + y * frame.h,
          3.5,
          0,
          Math.PI * 2,
        );
        context.fillStyle = color;
        context.fill();
        context.font = "11px sans-serif";
        context.fillStyle = "#fff";
        context.fillText(
          String(i + 1),
          frame.x + x * frame.w + 5,
          frame.y + y * frame.h - 5,
        );
      });
    }
    regions.forEach((r) =>
      polygon(r.polygon, r.type === "exclusion" ? "#ff8e95" : "#6de2b8", true),
    );
    polygon(
      points,
      $("#roiType").value === "exclusion" ? "#ff8e95" : "#f3d68b",
      false,
    );
  }
  function applyConfig(cfg) {
    regions = structuredClone(cfg.rois || []);
    points = [];
    drawing = false;
    $("#freeMax").value = cfg.calibration?.free_max ?? "";
    $("#busyMax").value = cfg.calibration?.busy_max ?? "";
    $("#jamMin").value = cfg.calibration?.jam_min ?? "";
    $("#calibrationConfirmed").checked = !!cfg.calibration_confirmed;
    renderRegions();
  }
  async function loadCamera(id, { skipGuard = false } = {}) {
    if (!skipGuard && !(await canLeave())) {
      $("#cameraSelect").value = camera;
      return;
    }
    const token = ++loadToken;
    if (!id) {
      camera = "";
      bitmap = null;
      regions = [];
      points = [];
      initial = "";
      $("#roiPlaceholder").hidden = false;
      renderRegions();
      return;
    }
    const cfg = await api("/api/cameras/" + encodeURIComponent(id) + "/roi"),
      row = cameras.find((c) => c.camera_id === id),
      image = new Image();
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = () =>
        reject(Error("Ảnh camera không còn đọc được. Khôi phục ảnh nguồn."));
      image.src = "/api/images/" + row.preview_id + "/file";
    });
    if (token !== loadToken) return;
    camera = id;
    bitmap = image;
    $("#cameraSelect").value = id;
    $("#roiPlaceholder").hidden = true;
    applyConfig(cfg);
    initial = JSON.stringify(config());
  }
  async function loadCameras() {
    cameras = await api("/api/cameras");
    $("#cameraSelect").innerHTML = cameras.length
      ? cameras
          .map(
            (c) =>
              `<option value="${esc(c.camera_id)}">${esc(c.camera_id)} · ${number(c.image_count)} ảnh</option>`,
          )
          .join("")
      : '<option value="">Chưa có camera</option>';
    if (cameras.some((c) => c.camera_id === camera)) {
      $("#cameraSelect").value = camera;
      draw();
    } else await loadCamera(cameras[0]?.camera_id || "", { skipGuard: true });
  }
  async function save() {
    if (!camera) throw Error("Nhập ảnh trước khi cấu hình camera.");
    if (points.length) throw Error("Khép vùng đang vẽ trước khi lưu cấu hình.");
    const values = ["freeMax", "busyMax", "jamMin"].map(
      (id) => $("#" + id).value,
    );
    if (values.some((v) => v === "") && !values.every((v) => v === ""))
      throw Error("Điền đủ cả 3 ngưỡng hoặc để trống cả 3.");
    const result = await api(
      "/api/cameras/" + encodeURIComponent(camera) + "/roi",
      { method: "PUT", body: JSON.stringify({ config: config() }) },
    );
    applyConfig(result);
    initial = JSON.stringify(config());
    toast("Đã lưu ROI và ngưỡng camera. Chạy phân tích để cập nhật đặc trưng.");
  }
  async function loadTable(reset = false) {
    if (reset) offset = 0;
    const token = ++tableToken;
    const result = await api(
      `/api/traffic/labels?limit=30&offset=${offset}&review_only=${$("#trafficReviewOnly").checked}`,
    );
    if (token !== tableToken) return;
    total = result.total;
    $("#trafficPage").textContent =
      `${total ? offset + 1 : 0}–${Math.min(offset + 30, total)} / ${number(total)} ảnh`;
    $('[data-action="traffic-prev"]').disabled = offset === 0;
    $('[data-action="traffic-next"]').disabled = offset + 30 >= total;
    $("#trafficTable").innerHTML = result.items.length
      ? `<table><thead><tr><th>ẢNH / CAMERA</th><th>XE TRONG ROI</th><th>TRẠNG THÁI</th><th>NHÃN GIAO THÔNG</th></tr></thead><tbody>${result.items
          .map((row) => {
            const f = row.features,
              idx = names.indexOf(row.predicted_class);
            return `<tr><td><button class="table-image" data-open-image="${row.image_id}"><img src="/api/images/${row.image_id}/thumbnail" loading="lazy" alt=""><span><b>${esc(basename(row.rel_path))}</b><small>${esc(row.camera_id)}</small></span></button></td><td><b>${number(f.total_vehicle_count)}</b><div class="traffic-reasons">Box proxy: ${f.box_occupancy_proxy == null ? "chưa có" : Math.round(f.box_occupancy_proxy * 100) + "%"}${f.features_stale ? " · Cần phân tích lại" : ""}</div></td><td><span class="pill ${row.review_status === "accepted" ? "mint" : "amber"}">${esc(statusLabel(row.review_status))}</span><div class="traffic-reasons">${esc((f.reasons || []).map((r) => reasons[r] || r).join(" · "))}</div></td><td><div class="traffic-label-controls"><select id="traffic-label-${row.image_id}" aria-label="Nhãn traffic ảnh ${row.image_id}"><option value="" ${idx < 0 ? "selected" : ""}>Chọn nhãn…</option>${names.map((name, i) => `<option value="${name}" ${i === idx ? "selected" : ""}>${labels[i]}</option>`).join("")}</select><button class="primary" data-action="confirm-traffic" data-id="${row.image_id}">Xác nhận</button><button class="secondary" data-action="reject-traffic" data-id="${row.image_id}" aria-label="Loại nhãn traffic ảnh ${row.image_id}">Loại</button></div></td></tr>`;
          })
          .join("")}</tbody></table>`
      : empty(
          "Chưa có trạng thái giao thông",
          "Cấu hình ROI, ngưỡng của camera rồi bấm Phân tích traffic.",
        );
  }
  async function verify(id, accepted) {
    const label = $("#traffic-label-" + id).value;
    if (!label) throw Error("Chọn nhãn giao thông trước khi xác nhận.");
    await api("/api/traffic/labels/" + id, {
      method: "PUT",
      body: JSON.stringify({ label, accepted }),
    });
    toast(
      accepted
        ? "Đã xác nhận nhãn classification."
        : "Đã loại nhãn classification.",
    );
    await loadTable();
    await onChanged();
  }
  $("#cameraSelect").addEventListener("change", (event) =>
    loadCamera(event.target.value).catch((e) => toast(e.message, true)),
  );
  $("#roiRegions").addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-roi]");
    if (button) {
      regions.splice(Number(button.dataset.removeRoi), 1);
      renderRegions();
    }
  });
  ["freeMax", "busyMax", "jamMin", "calibrationConfirmed"].forEach((id) =>
    $("#" + id).addEventListener(
      "input",
      () => ($("#roiJson").value = JSON.stringify(config(), null, 2)),
    ),
  );
  $("#trafficReviewOnly").addEventListener("change", () =>
    loadTable(true).catch((e) => toast(e.message, true)),
  );
  canvas.addEventListener("pointerdown", (event) => {
    if (!bitmap || !drawing) return;
    const rect = canvas.getBoundingClientRect(),
      x = (event.clientX - rect.left - frame.x) / frame.w,
      y = (event.clientY - rect.top - frame.y) / frame.h;
    if (x < 0 || y < 0 || x > 1 || y > 1) return;
    event.preventDefault();
    points.push([Number(x.toFixed(5)), Number(y.toFixed(5))]);
    draw();
  });
  new ResizeObserver(draw).observe(canvas.parentElement);
  window.addEventListener("beforeunload", (event) => {
    if (dirty()) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  const actions = {
    "roi-new": () => {
      if (!camera) throw Error("Nhập ảnh trước để có camera.");
      points = [];
      drawing = true;
      draw();
      toast("Click các điểm theo biên vùng rồi bấm Khép vùng.");
    },
    "roi-finish": () => {
      if (points.length < 3) throw Error("Vùng cần ít nhất 3 điểm.");
      regions.push({
        name: $("#roiType").value + "_" + (regions.length + 1),
        type: $("#roiType").value,
        status: "confirmed",
        polygon: points,
      });
      points = [];
      drawing = false;
      renderRegions();
    },
    "roi-undo": () => {
      points.pop();
      draw();
    },
    "apply-roi-json": () => {
      const value = JSON.parse($("#roiJson").value);
      if (!Array.isArray(value.rois))
        throw Error("JSON phải chứa danh sách rois.");
      if (
        value.rois.some(
          (r) =>
            !Array.isArray(r.polygon) ||
            r.polygon.some(
              (p) =>
                !Array.isArray(p) ||
                p.length !== 2 ||
                p.some((v) => typeof v !== "number" || !Number.isFinite(v)),
            ),
        )
      )
        throw Error("Tọa độ polygon không hợp lệ.");
      applyConfig(value);
      toast("Đã áp dụng vào biểu mẫu. Bấm Lưu cấu hình để xác nhận.");
    },
    "analyze-traffic": async () => {
      if (dirty()) throw Error("Lưu cấu hình ROI trước khi phân tích.");
      await runTask("/api/traffic/analyze?background=true", {});
    },
    "confirm-traffic": (button) => verify(Number(button.dataset.id), true),
    "reject-traffic": (button) => verify(Number(button.dataset.id), false),
    "traffic-prev": async () => {
      offset = Math.max(0, offset - 30);
      await loadTable();
    },
    "traffic-next": async () => {
      if (offset + 30 < total) {
        offset += 30;
        await loadTable();
      }
    },
  };
  return { actions, loadCameras, loadTable, save, dirty, canLeave, draw };
}
