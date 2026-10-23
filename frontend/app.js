import {
  $,
  $$,
  api,
  esc,
  icon,
  renderIcons,
  classes,
  colors,
  number,
  basename,
  statusLabel,
  dateLabel,
  toast,
  empty,
  withBusy,
  confirmAction,
  safeStorage,
  debounce,
} from "./api.js";
import { createEditor } from "./editor.js";
import { createTraffic } from "./traffic.js";

const titles = {
  dashboard: "Tổng quan",
  dataset: "Thư viện ảnh",
  labeling: "Gán nhãn AI",
  review: "Kiểm duyệt",
  traffic: "Traffic & ROI",
  export: "Xuất dataset",
  activity: "Nhật ký hệ thống",
};
let current = "dashboard",
  stats = null,
  hardware = null,
  imageOffset = 0,
  imageTotal = 0,
  imageToken = 0,
  gridMode = true,
  polling = false,
  healthTime = 0;
let activeTask = null,
  reportedTask = null,
  lastJobState = null;
const PAGE = 48;
renderIcons();
const editor = createEditor({ navigate, onChanged: refresh });
const traffic = createTraffic({ runTask, onChanged: refresh });

async function navigate(view, { skipGuard = false } = {}) {
  if (!titles[view]) view = "dashboard";
  const changingView = current !== view;
  if (current !== view && !skipGuard) {
    if (current === "review" && !(await editor.canLeave())) return false;
    if (current === "traffic" && !(await traffic.canLeave())) return false;
  }
  current = view;
  $$(".view").forEach((node) => {
    node.hidden = node.id !== view;
    node.classList.toggle("active", node.id === view);
  });
  $$(".nav-item").forEach((button) => {
    const selected = button.dataset.view === view;
    button.classList.toggle("active", selected);
    if (selected) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  $("#pageTitle").textContent = titles[view];
  $("#breadcrumb").textContent = titles[view];
  document.title = titles[view] + " · AutoLabel AI Studio";
  history.replaceState(null, "", "#" + view);
  if (changingView) window.scrollTo({ top: 0, behavior: "instant" });
  if (view === "dataset") await loadImages();
  if (view === "review") {
    await editor.loadQueue();
    editor.resize();
    editor.fit();
  }
  if (view === "traffic") {
    await traffic.loadCameras();
    await traffic.loadTable();
    traffic.draw();
  }
  if (view === "export") await loadExports();
  if (view === "activity") await loadLogs();
  return true;
}
function storeSettings() {
  const ids = [
    "datasetPath",
    "yoloPath",
    "deviceSelect",
    "dinoPath",
    "samPath",
    "confidence",
    "matchIou",
    "dinoBox",
    "dinoText",
    "proposalPath",
    "exportName",
    "exportDir",
    "splitMethod",
    "valFraction",
  ];
  const value = Object.fromEntries(ids.map((id) => [id, $("#" + id).value]));
  value.mode = $('input[name="mode"]:checked').value;
  safeStorage("autolabel.settings.v04", value);
}
function restoreSettings() {
  const value = safeStorage("autolabel.settings.v04") || {};
  for (const [id, val] of Object.entries(value)) {
    if (id === "mode") {
      const radio = $(
        `input[name="mode"][value="${["cpu_fast", "standard", "small_object", "high_accuracy"].includes(val) ? val : "standard"}"]`,
      );
      if (radio) radio.checked = true;
    } else if ($("#" + id) && typeof val === "string") $("#" + id).value = val;
  }
}
restoreSettings();
function renderHealth(h) {
  hardware = h;
  $("#deviceMini").textContent = h.gpu || "CPU";
  $("#deviceDetail").textContent =
    `${h.inference_device || h.device} · ${h.torch_available ? "AI runtime sẵn sàng" : "Chế độ web / kiểm duyệt"}`;
  if (!$("#yoloPath").value && h.default_yolo)
    $("#yoloPath").value = h.default_yolo;
  const memory = h.ram_total_mb
    ? `${(h.ram_used_mb / 1024).toFixed(1)} / ${(h.ram_total_mb / 1024).toFixed(1)} GB`
    : "Chưa có thông tin";
  const metric = (label, value, used, total) =>
    `<div class="hardware-metric"><div><span>${label}</span><b>${esc(value)}</b></div><div class="progress-track"><span style="width:${total ? Math.min(100, (100 * used) / total) : 0}%"></span></div></div>`;
  $("#hardwareDetails").innerHTML =
    `<div class="hardware-main">${icon("cpu")}<div><b>${esc(h.gpu || "Bộ xử lý CPU")}</b><small>${esc(h.inference_device || h.device)} · ${h.cpu_count || "—"} luồng hệ thống</small></div></div>${metric("RAM", memory, h.ram_used_mb, h.ram_total_mb)}${h.vram_total_mb ? metric("VRAM", `${number(h.vram_used_mb)} / ${number(h.vram_total_mb)} MiB`, h.vram_used_mb, h.vram_total_mb) : ""}<div class="hardware-info"><span>Python / hệ điều hành</span><b>${esc(h.python)} / ${esc(h.os?.split("-")[0])}</b></div><div class="hardware-info"><span>PyTorch</span><b>${h.torch_available ? esc(h.torch_version) : "Chưa cài"}</b></div><div class="hardware-info"><span>Ultralytics</span><b>${h.ultralytics_available ? "Sẵn sàng" : "Chưa cài"}</b></div><div class="hardware-info"><span>YOLO đang tải</span><b>${esc(basename(h.yolo_loaded) || "Chưa có")}</b></div>${h.fallback_reason ? `<div class="notice danger-note">Đã chuyển CPU: ${esc(h.fallback_reason)}</div>` : ""}${h.warnings?.length ? `<div class="notice" style="margin:15px">${h.warnings.map(esc).join("<br>")}</div>` : ""}`;
}
function jobControls(job) {
  if (!job) return "";
  const state = job.state,
    live = job.worker_alive;
  const actions = [];
  if (live && state === "running") actions.push(["pause", "Tạm dừng"]);
  if (
    ["paused", "pausing"].includes(state) ||
    (!live && ["stopped", "failed", "completed_with_errors"].includes(state))
  )
    actions.push(["resume", "Tiếp tục"]);
  if (live && ["running", "paused", "pausing"].includes(state))
    actions.push(["stop", "Dừng an toàn"], ["cancel", "Hủy job"]);
  return actions
    .map(
      ([action, label]) =>
        `<button class="secondary small ${action === "cancel" ? "danger-text" : ""}" data-action="job-${action}">${label}</button>`,
    )
    .join("");
}
function taskProgress(task) {
  const percent = task.total
    ? Math.min(100, Math.round((100 * task.completed) / task.total))
    : 0;
  return `<div><b>${esc({ import: "Đang nhập ảnh", export_detection: "Đang xuất detection", export_classification: "Đang xuất classification", export_temporal: "Đang xuất CSV", traffic_analysis: "Đang phân tích traffic", model_check: "Đang kiểm tra model", clear: "Đang làm mới workspace" }[task.kind] || "Đang xử lý")}</b><small>${esc(task.message || "Đang chuẩn bị…")}</small></div><div><div class="progress-track"><span style="width:${percent}%"></span></div><div class="progress-meta"><span>${task.total ? number(task.completed) + " / " + number(task.total) : "Đang quét / chuẩn bị"}</span><b>${task.total ? percent + "%" : "…"}</b></div></div><span class="pill mint">CHẠY NỀN</span>`;
}
function jobProgress(job) {
  return `<div><b>Job #${job.id} · ${esc(statusLabel(job.state))}</b><small>${esc(job.current_path || "Kết quả được lưu sau mỗi ảnh")}</small></div><div><div class="progress-track"><span style="width:${Math.min(100, job.percent || 0)}%"></span></div><div class="progress-meta"><span>${number(job.processed)} thành công · ${number(job.failed)} lỗi / ${number(job.total)}</span><b>${job.percent || 0}%</b></div></div><div class="job-actions">${jobControls(job)}</div>`;
}
function renderStats(s) {
  stats = s;
  const states = s.review_states || {},
    count = s.images || 0,
    reviewed = s.reviewed_images || 0,
    needs = states.unreviewed || 0;
  $("#statImages").textContent = number(count);
  $("#statProcessed").textContent = number(s.statuses.processed);
  $("#statReviewed").textContent = number(reviewed);
  $("#statReview").textContent = number(needs);
  $("#navReview").textContent = number(needs);
  $("#statPending").textContent =
    `${number(s.statuses.pending)} chờ xử lý · ${number(s.errors)} lỗi dữ liệu`;
  $("#statNegative").textContent =
    `${number(states.negative)} ảnh không có xe đã xác nhận`;
  const pct = count ? Math.round((100 * reviewed) / count) : 0;
  $("#reviewPercent").textContent = pct + "%";
  $("#reviewRing").style.background =
    `conic-gradient(var(--primary) ${pct * 3.6}deg,var(--ring) 0deg)`;
  $("#reviewSummary").textContent = count
    ? `${number(reviewed)} / ${number(count)} ảnh đã được duyệt`
    : "Bắt đầu bằng việc nhập ảnh";
  $("#objectTotal").textContent = number(s.objects) + " nhãn";
  const max = Math.max(1, ...classes.map((c) => s.classes[c] || 0));
  $("#classChart").innerHTML = classes
    .map(
      (c) =>
        `<div class="class-row"><span><i style="background:${colors[c]}"></i>${c}</span><div class="bar-track"><span style="width:${(100 * (s.classes[c] || 0)) / max}%;background:${colors[c]}"></span></div><b>${number(s.classes[c])}</b></div>`,
    )
    .join("");
  $("#recentImages").innerHTML = s.recent_images.length
    ? s.recent_images
        .map(
          (row) =>
            `<button class="recent-card" data-open-image="${row.id}"><img src="/api/images/${row.id}/thumbnail" alt="${esc(basename(row.rel_path))}" loading="lazy"><div><b>${esc(basename(row.rel_path))}</b><small>${row.object_count} box · ${statusLabel(row.review_state)}</small></div></button>`,
        )
        .join("")
    : empty(
        "Workspace đang chờ những bức ảnh đầu tiên",
        "Nhập một thư mục để quét ảnh, đọc nhãn có sẵn và bắt đầu quy trình.",
        "go-dataset",
        "Nhập ảnh đầu tiên",
      );
  const job = s.job;
  $("#jobOverview").innerHTML = job
    ? `<div class="progress-meta"><b>Job #${job.id}</b><span class="pill ${job.state === "failed" ? "red" : "mint"}">${esc(statusLabel(job.state))}</span></div><div class="progress-track"><span style="width:${Math.min(100, job.percent || 0)}%"></span></div><div class="progress-meta"><span>${number(job.processed)} / ${number(job.total)} ảnh · ${number(job.failed)} lỗi</span><b>${job.percent || 0}%</b></div><p class="job-file" title="${esc(job.current_path)}">${esc(job.current_path || job.error || "Kết quả đã được lưu vào workspace.")}</p><div class="job-actions">${jobControls(job)}</div>${job.seconds_per_image ? `<p class="hint">${job.seconds_per_image.toFixed(2)} giây/ảnh · ${job.worker_alive ? "còn khoảng " + number(job.eta_seconds) + " giây" : "thời gian xử lý trung bình"}</p>` : ""}`
    : `<div class="job-idle">${icon("spark")}<h3>Sẵn sàng khi bạn cần</h3><p>Chọn checkpoint và bắt đầu lượt gán nhãn đầu tiên.</p><button class="secondary small" data-view="labeling">Cấu hình mô hình <span>→</span></button></div>`;
  const task = s.task?.state === "running" ? s.task : null;
  const showJob =
    job && (job.worker_alive || ["paused", "stopped"].includes(job.state));
  $("#globalProgress").hidden = !task && !showJob;
  if (task) $("#globalProgress").innerHTML = taskProgress(task);
  else if (showJob) $("#globalProgress").innerHTML = jobProgress(job);
  const busy = Boolean(task || job?.worker_alive);
  for (const id of ["importButton", "startButton", "exportButton"]) {
    const button = $("#" + id);
    if (!button.classList.contains("busy")) button.disabled = busy;
  }
  if (
    lastJobState &&
    lastJobState !== job?.state &&
    [
      "completed",
      "completed_with_errors",
      "failed",
      "stopped",
      "cancelled",
    ].includes(job?.state)
  ) {
    toast(
      `Job #${job.id}: ${statusLabel(job.state)}${job.error ? " — " + job.error : ""}`,
      job.state === "failed",
    );
    if (current === "dataset")
      loadImages().catch((e) => toast(e.message, true));
    if (current === "review")
      editor.loadQueue().catch((e) => toast(e.message, true));
  }
  lastJobState = job?.state || null;
}
async function finishTask(task) {
  if (
    !task ||
    task.id !== activeTask ||
    task.state === "running" ||
    reportedTask === task.id
  )
    return;
  reportedTask = task.id;
  activeTask = null;
  if (task.state !== "completed") {
    toast(task.error || "Tác vụ bị gián đoạn.", true);
    const target = task.kind === "import" ? "#importResult" : "#exportResult";
    $(target).textContent = task.error || "Tác vụ bị gián đoạn";
    $(target).className = "result-message error";
    return;
  }
  const result = task.result || {};
  if (task.kind === "import") {
    $("#importResult").className = "result-message success";
    $("#importResult").textContent =
      `Đã thêm ${number(result.added)} ảnh · ${number(result.duplicates)} trùng bỏ qua${result.retained_duplicates ? " · " + number(result.retained_duplicates) + " frame trùng được giữ" : ""} · ${number(result.broken)} ảnh lỗi · ${number(result.label_errors)} lỗi nhãn. Xem Nhật ký để biết chi tiết.`;
    toast("Đã nhập ảnh. Bạn có thể gán nhãn AI hoặc kiểm duyệt thủ công.");
    await loadImages(true);
    if (current === "traffic") await traffic.loadCameras();
  } else if (task.kind.startsWith("export_")) {
    $("#exportResult").className = "result-message success";
    $("#exportResult").innerHTML =
      `<b>Đã tạo ${number(result.images || result.records)} ${result.records ? "bản ghi" : "ảnh"}.</b><p>${esc(result.path)}</p>${result.warnings?.length ? `<ul>${result.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}<a class="primary" href="${esc(result.download_url)}" download>${icon("download")} Tải ZIP</a>`;
    toast("Snapshot đã sẵn sàng để tải.");
    await loadExports();
  } else if (task.kind === "traffic_analysis") {
    toast(
      `Đã phân tích ${number(result.processed)} ảnh; ${number(result.needs_review)} ảnh cần duyệt.`,
    );
    await traffic.loadTable(true);
  }
}
async function refresh() {
  if (polling) return;
  polling = true;
  try {
    const s = await api("/api/stats");
    renderStats(s);
    $("#connection").innerHTML = '<span class="dot"></span> Đã kết nối local';
    $("#connection").className = "connection";
    $("#connectionError").hidden = true;
    if (s.task?.state === "running" && activeTask === null)
      activeTask = s.task.id;
    try {
      await finishTask(s.task);
    } catch (error) {
      toast(
        "Tác vụ đã kết thúc, nhưng không làm mới được danh sách: " +
          error.message,
        true,
      );
    }
    if (!hardware || Date.now() - healthTime > 30000) {
      healthTime = Date.now();
      try {
        renderHealth(await api("/api/health"));
      } catch (e) {
        $("#deviceMini").textContent = "Không đọc được phần cứng";
      }
    }
  } catch (error) {
    $("#connection").innerHTML = '<span class="dot"></span> Mất kết nối';
    $("#connection").className = "connection offline";
    $("#connectionError").hidden = false;
  } finally {
    polling = false;
  }
}
async function loadImages(reset = false) {
  if (reset) imageOffset = 0;
  const token = ++imageToken;
  const query = new URLSearchParams({
    q: $("#imageSearch").value,
    status: $("#imageStatus").value,
    review: $("#imageReview").value,
    limit: PAGE,
    offset: imageOffset,
  });
  const result = await api("/api/images?" + query);
  if (token !== imageToken) return;
  imageTotal = result.total;
  $("#imageCount").textContent = number(imageTotal) + " ảnh trong bộ lọc";
  $("#imagePage").textContent =
    `${imageTotal ? imageOffset + 1 : 0}–${Math.min(imageOffset + PAGE, imageTotal)} / ${number(imageTotal)}`;
  $('[data-action="images-prev"]').disabled = imageOffset === 0;
  $('[data-action="images-next"]').disabled = imageOffset + PAGE >= imageTotal;
  const badge = (row) =>
    `<span class="pill ${row.error ? "red" : row.review_state !== "unreviewed" ? "mint" : row.status === "processing" ? "amber" : ""}">${esc(row.error ? "Cần xử lý lỗi" : row.review_state === "unreviewed" ? statusLabel(row.status) : statusLabel(row.review_state))}</span>`;
  if (!result.items.length) {
    $("#imageLibrary").innerHTML = empty(
      "Không có ảnh trong bộ lọc này",
      "Nhập thư mục ảnh hoặc thay đổi bộ lọc phía trên.",
    );
    return;
  }
  $("#imageLibrary").innerHTML = gridMode
    ? `<div class="image-grid">${result.items.map((row) => `<article class="image-card"><button data-open-image="${row.id}" title="${esc(row.error || row.rel_path)}"><div class="image-cover"><img src="/api/images/${row.id}/thumbnail" loading="lazy" alt="${esc(basename(row.rel_path))}">${badge(row)}</div><div class="image-card-info"><b>${esc(basename(row.rel_path))}</b><small>${esc(row.camera_id)} · ${row.width} × ${row.height}</small><div class="image-card-bottom"><span>${number(row.object_count)} đối tượng</span><span>Mở kiểm duyệt ↗</span></div></div></button></article>`).join("")}</div>`
    : `<div class="panel table-wrap"><table><thead><tr><th>ẢNH / CAMERA</th><th>KÍCH THƯỚC</th><th>NHÃN</th><th>TRẠNG THÁI</th><th></th></tr></thead><tbody>${result.items.map((row) => `<tr><td><button class="table-image" data-open-image="${row.id}"><img src="/api/images/${row.id}/thumbnail" loading="lazy" alt=""><span><b>${esc(basename(row.rel_path))}</b><small>${esc(row.camera_id)}</small></span></button></td><td>${row.width} × ${row.height}</td><td>${number(row.object_count)}</td><td title="${esc(row.error || "")}">${badge(row)}</td><td><button class="text-button" data-open-image="${row.id}">Kiểm duyệt →</button></td></tr>`).join("")}</tbody></table></div>`;
}
async function runTask(url, body) {
  const result = await api(url, {
    method: "POST",
    body: JSON.stringify({ ...body, background: true }),
  });
  activeTask = result.task_id;
  reportedTask = null;
  await refresh();
  return result;
}
async function importDataset() {
  const folder = $("#datasetPath").value.trim();
  if (!folder) throw Error("Nhập đường dẫn thư mục trên máy chạy server.");
  const clear = $("#clearFirst").checked;
  if (
    clear &&
    !(await confirmAction({
      title: "Thay thế dataset hiện tại?",
      body: "Danh sách ảnh và nhãn trong workspace sẽ được thay thế. Hệ thống sao lưu database trước khi xóa; ảnh nguồn được giữ nguyên.",
      confirmText: "Thay thế & nhập",
      danger: true,
      typeText: true,
    }))
  )
    return;
  storeSettings();
  $("#importResult").textContent = "Đang chuẩn bị nhập ảnh…";
  $("#importResult").className = "result-message";
  await runTask("/api/datasets/import", {
    folder,
    clear_first: clear,
    keep_duplicates: $("#keepDuplicates").checked,
  });
  $("#clearFirst").checked = false;
}
async function startJob() {
  storeSettings();
  const mode = $('input[name="mode"]:checked').value;
  if (
    $("#acceptYoloOnly").checked &&
    !(await confirmAction({
      title: "Chấp nhận dự đoán một mô hình?",
      body: "Nhãn YOLO-only chưa được kiểm chứng. Bạn vẫn cần kiểm duyệt trước khi dùng làm ground truth.",
      confirmText: "Chạy với pseudo-label",
    }))
  )
    return;
  const body = {
    yolo_model: $("#yoloPath").value.trim(),
    device: $("#deviceSelect").value,
    mode,
    imgsz: mode === "cpu_fast" ? 640 : mode === "high_accuracy" ? 1280 : 960,
    dino_model: $("#dinoPath").value.trim() || null,
    sam_model: $("#samPath").value.trim() || null,
    yolo_conf: Number($("#confidence").value),
    match_iou: Number($("#matchIou").value),
    dino_box_threshold: Number($("#dinoBox").value),
    dino_text_threshold: Number($("#dinoText").value),
    auto_accept: $("#autoAccept").checked,
    accept_yolo_only: $("#acceptYoloOnly").checked,
    output_dir: $("#proposalPath").value.trim() || null,
    analyze_traffic_after: $("#analyzeAfter").checked,
  };
  const result = await api("/api/jobs/start", {
    method: "POST",
    body: JSON.stringify(body),
  });
  $("#startResult").textContent =
    `Đã tạo job #${result.job_id}. Theo dõi tiến độ ở thanh phía trên.`;
  $("#startResult").className = "result-message success";
  toast("Job đang nạp checkpoint và chuẩn bị xử lý.");
  await refresh();
}
async function jobAction(action) {
  if (
    action === "cancel" &&
    !(await confirmAction({
      title: "Hủy phần còn lại của job?",
      body: "Worker sẽ kết thúc ảnh đang xử lý rồi dừng. Kết quả đã lưu được giữ nguyên. Dùng Dừng an toàn nếu bạn muốn tiếp tục cùng job sau này.",
      confirmText: "Hủy phần còn lại",
      danger: true,
    }))
  )
    return;
  await api("/api/jobs/" + action, { method: "POST" });
  await refresh();
}
async function exportData() {
  storeSettings();
  const type = $("#exportType").value,
    name = $("#exportName").value.trim(),
    include_pseudo = $("#includePseudo").checked;
  if (
    type !== "temporal" &&
    include_pseudo &&
    !(await confirmAction({
      title:
        type === "detection"
          ? "Xuất nhãn AI của ảnh đã xử lý?"
          : "Thêm pseudo-label vào bản xuất?",
      body:
        type === "detection"
          ? "Chỉ ảnh đã xử lý xong và có box hợp lệ được xuất. Ảnh pending, ảnh không có box và box không rõ lớp sẽ bị loại. Các nhãn này chưa được con người kiểm chứng."
          : "Snapshot sẽ ghi rõ nhãn AI chưa được người xác minh. Hãy kiểm tra chất lượng trước khi huấn luyện.",
      confirmText:
        type === "detection" ? "Xuất nhãn AI chưa duyệt" : "Xuất kèm pseudo-label",
    }))
  )
    return;
  $("#exportResult").textContent = "Đang chuẩn bị snapshot…";
  $("#exportResult").className = "result-message";
  const body = { name, include_pseudo };
  let url;
  if (type === "detection") {
    url = "/api/export";
    Object.assign(body, {
      output_dir: $("#exportDir").value.trim() || null,
      split_method: $("#splitMethod").value,
      val_fraction: Number($("#valFraction").value),
    });
  } else
    url =
      type === "classification"
        ? "/api/traffic/export-classification"
        : "/api/traffic/export";
  await runTask(url, body);
}
async function loadExports() {
  const result = await api("/api/exports");
  $("#exportHistory").innerHTML = result.items.length
    ? result.items
        .map(
          (row) =>
            `<div class="export-entry">${icon("download")}<div><b>${esc(basename(row.path))}</b><small>${esc({ detection: "YOLO Detection", classification: "Classification", temporal: "Traffic CSV" }[row.kind] || row.kind)} · ${number(row.summary.images || row.summary.records)} ${row.summary.records ? "bản ghi" : "ảnh"} · ${dateLabel(row.created_at)}</small>${row.summary.warnings?.length ? `<small>${row.summary.warnings.map(esc).join(" ")}</small>` : ""}</div><a class="secondary" href="${esc(row.download_url)}" download>${icon("download")} Tải ZIP</a></div>`,
        )
        .join("")
    : empty(
        "Chưa có bản xuất",
        "Tạo snapshot đầu tiên bằng biểu mẫu phía trên.",
      );
}
async function loadLogs() {
  const result = await api("/api/logs?limit=100&level=" + $("#logLevel").value);
  $("#logList").innerHTML = result.items.length
    ? result.items
        .map(
          (row) =>
            `<div class="log-entry"><time>${dateLabel(row.created_at)}</time><span class="pill ${row.level === "error" ? "red" : row.level === "warning" ? "amber" : ""}">${esc({ error: "Lỗi", warning: "Cảnh báo", info: "Thông tin" }[row.level] || row.level)}</span><p>${esc(row.message)}</p>${row.image_id ? `<button class="text-button" data-open-image="${row.image_id}">Mở ảnh →</button>` : ""}</div>`,
        )
        .join("")
    : empty(
        "Chưa có sự kiện",
        "Các hoạt động và lỗi phát sinh sẽ được ghi tại đây.",
      );
}
function updateExportType() {
  const value = $("#exportType").value;
  $("#detectionExportFields").hidden = value !== "detection";
  $("#pseudoOption").hidden = value === "temporal";
  $("#stopExportHint").hidden = value !== "detection";
  $("#pseudoLabelText").textContent =
    value === "detection"
      ? "nhãn AI của ảnh đã xử lý xong, kể cả box chưa chấp nhận"
      : "pseudo-label chưa được con người xác minh";
  $("#exportPolicy").textContent =
    value === "detection"
      ? "Mặc định: ảnh đã duyệt hoàn chỉnh và nhãn YOLO nhập hợp lệ. Khi bật pseudo-label, xuất tất cả box AI hợp lệ trên ảnh đã xử lý xong; ảnh pending và dự đoán rỗng bị loại."
      : value === "classification"
        ? "Mặc định chỉ xuất classification được con người xác nhận. Tách nhóm theo camera/ngày, khoảng 80% train và 20% validation."
        : "Xuất tất cả quan sát có timestamp hợp lệ, kèm trạng thái duyệt và nguồn nhãn. Cần phân tích lại nếu ROI hoặc box đã thay đổi.";
}
const actions = {
  ...editor.actions,
  ...traffic.actions,
  "go-dataset": () => navigate("dataset"),
  "open-first": () => editor.first(),
  "review-needed": async () => {
    $("#queueFilter").value = "needs_review";
    await navigate("review");
    await editor.first();
  },
  theme: () => {
    const theme =
      document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("autolabel.theme", theme);
    } catch {}
    $("#themeToggle").setAttribute(
      "aria-label",
      theme === "dark" ? "Chuyển giao diện sáng" : "Chuyển giao diện tối",
    );
  },
  refresh: async () => {
    healthTime = 0;
    await refresh();
    if (current === "dataset") await loadImages();
    if (current === "activity") await loadLogs();
    if (current === "export") await loadExports();
  },
  "grid-mode": async () => {
    gridMode = true;
    setGridMode();
    await loadImages();
  },
  "table-mode": async () => {
    gridMode = false;
    setGridMode();
    await loadImages();
  },
  "images-prev": async () => {
    imageOffset = Math.max(0, imageOffset - PAGE);
    await loadImages();
  },
  "images-next": async () => {
    if (imageOffset + PAGE < imageTotal) {
      imageOffset += PAGE;
      await loadImages();
    }
  },
  "clear-dataset": async () => {
    if (
      !(await confirmAction({
        title: "Làm mới toàn bộ workspace?",
        body: "Xóa danh sách ảnh, annotation và lịch sử review khỏi workspace hiện tại. Database được sao lưu trước; ảnh gốc và snapshot đã xuất vẫn được giữ.",
        confirmText: "Làm mới workspace",
        danger: true,
        typeText: true,
      }))
    )
      return;
    const result = await api("/api/datasets/clear", { method: "POST" });
    editor.clear();
    await loadImages(true);
    await refresh();
    toast("Đã làm mới. Database sao lưu: " + result.backup);
  },
  "check-model": async () => {
    storeSettings();
    $("#modelResult").textContent = "Đang nạp checkpoint và kiểm tra tên lớp…";
    try {
      const result = await api(
        "/api/model/check?" +
          new URLSearchParams({
            path: $("#yoloPath").value,
            device: $("#deviceSelect").value,
          }),
      );
      $("#modelResult").textContent =
        `Checkpoint hợp lệ · ${result.device} · ${Object.values(result.names).join(", ")}`;
      toast("Checkpoint hợp lệ.");
    } catch (e) {
      $("#modelResult").textContent = e.message;
      throw e;
    }
  },
  "job-pause": () => jobAction("pause"),
  "job-resume": () => jobAction("resume"),
  "job-stop": () => jobAction("stop"),
  "job-cancel": () => jobAction("cancel"),
  "load-exports": loadExports,
  help: () =>
    confirmAction({
      title: "Bắt đầu với AutoLabel",
      body: "1. Nhập thư mục ảnh trên máy chạy server.\n2. Cấu hình best.pt để gán nhãn AI, hoặc sửa nhãn thủ công ngay.\n3. Kiểm duyệt đầy đủ ảnh rồi lưu xác nhận. Ảnh không có xe cần đánh dấu riêng.\n4. Xuất snapshot và tải ZIP.",
      info: true,
      extra:
        "<p>Trong editor: <kbd>B</kbd> vẽ box · <kbd>V</kbd> chọn · <kbd>F</kbd> vừa khung · <kbd>1–5</kbd> đổi lớp · <kbd>Delete</kbd> xóa · <kbd>Ctrl/Cmd Z</kbd> hoàn tác · <kbd>Ctrl/Cmd S</kbd> lưu.</p><p>Cuộn để zoom; giữ Space và kéo để di chuyển ảnh. DINO/SAM là tùy chọn. Traffic hiện dùng quy tắc theo camera, cần xác nhận bằng con người.</p>",
    }),
};
function setGridMode() {
  for (const [name, active] of [
    ["grid", gridMode],
    ["table", !gridMode],
  ]) {
    const button = $(`[data-action="${name}-mode"]`);
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
}
document.addEventListener("click", async (event) => {
  const open = event.target.closest("[data-open-image]");
  if (open) {
    event.preventDefault();
    try {
      if (current === "traffic" && !(await traffic.canLeave())) return;
      await editor.open(Number(open.dataset.openImage));
    } catch (e) {
      toast(e.message, true);
    }
    return;
  }
  const view = event.target.closest("[data-view]");
  if (view) {
    event.preventDefault();
    try {
      await navigate(view.dataset.view);
    } catch (e) {
      toast(e.message, true);
    }
    return;
  }
  const action = event.target.closest("[data-action]");
  if (!action || !actions[action.dataset.action]) return;
  event.preventDefault();
  try {
    await withBusy(action, () => actions[action.dataset.action](action));
  } catch (e) {
    toast(e.message, true);
  }
});
for (const [selector, fn] of [
  ["#importForm", importDataset],
  ["#modelForm", startJob],
  ["#exportForm", exportData],
  ["#roiForm", traffic.save],
]) {
  $(selector).addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.submitter || $(selector + ' button[type="submit"]');
    try {
      await withBusy(button, fn);
    } catch (e) {
      toast(e.message, true);
      const target =
        selector === "#importForm"
          ? "#importResult"
          : selector === "#modelForm"
            ? "#startResult"
            : selector === "#exportForm"
              ? "#exportResult"
              : null;
      if (target) {
        $(target).textContent = e.message;
        $(target).className = "result-message error";
      }
    }
  });
}
$("#imageSearch").addEventListener(
  "input",
  debounce(() => loadImages(true).catch((e) => toast(e.message, true))),
);
["imageStatus", "imageReview"].forEach((id) =>
  $("#" + id).addEventListener("change", () =>
    loadImages(true).catch((e) => toast(e.message, true)),
  ),
);
$("#logLevel").addEventListener("change", () =>
  loadLogs().catch((e) => toast(e.message, true)),
);
$("#exportType").addEventListener("change", updateExportType);
for (const [id, out] of [
  ["confidence", "confValue"],
  ["matchIou", "iouValue"],
]) {
  $("#" + id).addEventListener(
    "input",
    () => ($("#" + out).textContent = Number($("#" + id).value).toFixed(2)),
  );
  $("#" + out).textContent = Number($("#" + id).value).toFixed(2);
}
$("#modelForm").addEventListener("change", storeSettings);
$(".brand").addEventListener("click", (event) => {
  event.preventDefault();
  navigate("dashboard").catch((e) => toast(e.message, true));
});
window.addEventListener("hashchange", () =>
  navigate(location.hash.slice(1)).catch((e) => toast(e.message, true)),
);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh();
});
await refresh();
await navigate(location.hash.slice(1) || "dashboard");
setInterval(() => {
  if (!document.hidden) refresh();
}, 3000);
