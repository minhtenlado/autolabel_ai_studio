export const $ = (selector) => document.querySelector(selector);
export const $$ = (selector) => [...document.querySelectorAll(selector)];
export const classes = ["bus", "car", "container", "motorcycle", "truck"];
export const colors = {
  bus: "#2f9e8a",
  car: "#5799d7",
  container: "#9b88cf",
  motorcycle: "#d9ab5d",
  truck: "#d4847f",
  ambiguous: "#ee7272",
};
export const number = (value) => Number(value || 0).toLocaleString("vi-VN");
export const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
export const basename = (path) =>
  String(path || "")
    .split(/[\\/]/)
    .pop();
export const dateLabel = (date) =>
  date
    ? new Date(
        date.includes("T") ? date : date.replace(" ", "T") + "Z",
      ).toLocaleString("vi-VN")
    : "—";
export const statusLabels = {
  pending: "Chờ xử lý",
  processing: "Đang xử lý",
  processed: "Đã xử lý",
  failed: "Lỗi",
  unreviewed: "Chưa kiểm duyệt",
  reviewed: "Đã kiểm duyệt",
  negative: "Không có xe",
  running: "Đang chạy",
  pausing: "Đang tạm dừng",
  paused: "Đã tạm dừng",
  stopping: "Đang dừng",
  stopped: "Đã dừng",
  cancelling: "Đang hủy",
  cancelled: "Đã hủy",
  completed: "Hoàn tất",
  completed_with_errors: "Hoàn tất, có lỗi",
  interrupted: "Bị gián đoạn",
  accepted: "Đã xác nhận",
  rejected: "Đã loại",
  high_quality_candidate: "Gợi ý đủ điều kiện",
  needs_review: "Cần kiểm duyệt",
};
export const statusLabel = (key) => statusLabels[key] || key || "—";
export const iconPaths = {
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  image:
    '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m21 15-5-5L5 21"/>',
  spark:
    '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/><path d="M20 2v4M18 4h4"/>',
  scan: '<path d="M8 3H4a1 1 0 0 0-1 1v4m13-5h4a1 1 0 0 1 1 1v4M3 16v4a1 1 0 0 0 1 1h4m8 0h4a1 1 0 0 0 1-1v-4"/><rect x="7" y="7" width="10" height="10" rx="1"/>',
  download:
    '<path d="M12 3v12m-5-5 5 5 5-5M4 16v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4"/>',
  route:
    '<circle cx="5" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><path d="M7 5h10a4 4 0 0 1 0 8H7a3 3 0 0 0 0 6h10"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9" y="9" width="6" height="6" rx="1"/><path d="M9 3v3m6-3v3M9 18v3m6-3v3M3 9h3m-3 6h3m12-6h3m-3 6h3"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9 9a3 3 0 0 1 6 0c0 2-3 2-3 4m0 3h.01"/>',
  moon: '<path d="M20.8 13A9 9 0 0 1 11 3.2 9 9 0 1 0 20.8 13Z"/>',
  refresh:
    '<path d="M20 10a8 8 0 0 0-14-5L3 8m0-5v5h5M4 14a8 8 0 0 0 14 5l3-3m0 5v-5h-5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  shield:
    '<path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6l-8-3Z"/><path d="m8 12 3 3 5-6"/>',
  chevron: '<path d="m9 5 7 7-7 7"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  folder:
    '<path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/><path d="M3 9h18"/>',
  search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
  trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
  leaf: '<path d="M20 3C9 3 3 7 4 14s12 10 16-11ZM4 21 15 10"/>',
  play: '<path d="m7 4 14 8-14 8V4Z"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>',
  undo: '<path d="m8 3-5 5 5 5M3 8h11a6 6 0 0 1 0 12h-3"/>',
  redo: '<path d="m16 3 5 5-5 5m5-5H10a6 6 0 0 0 0 12h3"/>',
  expand: '<path d="M8 3H3v5m13-5h5v5M3 16v5h5m8 0h5v-5"/>',
  pointer: '<path d="m4 3 6 18 3-8 8-3L4 3Z"/>',
  hand: '<path d="M8 13V6a2 2 0 0 1 4 0v6-8a2 2 0 0 1 4 0v8-6a2 2 0 0 1 4 0v9c0 5-3 7-7 7-3 0-5-2-7-5l-3-5a2 2 0 0 1 3-2l2 3Z"/>',
};
export const icon = (name) =>
  `<i aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${iconPaths[name] || iconPaths.info}</svg></i>`;
export function renderIcons(root = document) {
  root.querySelectorAll("i[data-icon]").forEach((node) => {
    node.innerHTML = icon(node.dataset.icon).replace(/^<i[^>]*>|<\/i>$/g, "");
    node.setAttribute("aria-hidden", "true");
  });
}
export async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  let body;
  try {
    body = await response.json();
  } catch {
    body = {};
  }
  if (!response.ok) {
    const detail = Array.isArray(body.detail)
      ? body.detail
          .map((x) => `${x.loc?.slice(1).join(".")}: ${x.msg}`)
          .join("; ")
      : body.detail;
    const error = new Error(
      detail || `Không hoàn tất yêu cầu (HTTP ${response.status}).`,
    );
    error.status = response.status;
    throw error;
  }
  return body;
}
export function toast(message, error = false) {
  const node = document.createElement("div");
  node.className = "toast" + (error ? " error" : "");
  const span = document.createElement("span");
  span.textContent = message;
  const close = document.createElement("button");
  close.textContent = "×";
  close.setAttribute("aria-label", "Đóng thông báo");
  close.onclick = () => node.remove();
  node.append(span, close);
  $("#toasts").append(node);
  while ($("#toasts").children.length > 3)
    $("#toasts").firstElementChild.remove();
  setTimeout(() => node.remove(), error ? 12000 : 6500);
}
export function empty(title, body, action = "", label = "") {
  return `<div class="empty-state">${icon("image")}<h3>${esc(title)}</h3><p>${esc(body)}</p>${action ? `<button class="primary" data-action="${esc(action)}">${esc(label)}</button>` : ""}</div>`;
}
export async function withBusy(button, fn) {
  if (button?.disabled) return;
  if (button) {
    button.disabled = true;
    button.classList.add("busy");
    button.setAttribute("aria-busy", "true");
  }
  try {
    return await fn();
  } finally {
    if (button) {
      button.disabled = false;
      button.classList.remove("busy");
      button.removeAttribute("aria-busy");
    }
  }
}
export function confirmAction({
  title,
  body,
  confirmText = "Tiếp tục",
  danger = false,
  typeText = false,
  extra = "",
  info = false,
}) {
  const dialog = $("#confirmDialog");
  if (dialog.open) return Promise.resolve(false);
  $("#dialogTitle").textContent = title;
  $("#dialogBody").textContent = body;
  $("#dialogExtra").innerHTML = extra;
  const confirm = $("#dialogConfirm");
  confirm.textContent = confirmText;
  confirm.className = "primary" + (danger ? " danger" : "");
  confirm.hidden = info;
  confirm.disabled = typeText;
  $("#confirmTextLabel").hidden = !typeText;
  $("#confirmText").value = "";
  $("#confirmText").oninput = () =>
    (confirm.disabled = $("#confirmText").value.trim() !== "XÓA");
  dialog.returnValue = "cancel";
  dialog.showModal();
  return new Promise((resolve) =>
    dialog.addEventListener(
      "close",
      () => resolve(dialog.returnValue === "confirm"),
      { once: true },
    ),
  );
}
export function safeStorage(key, value) {
  try {
    if (value === undefined)
      return JSON.parse(localStorage.getItem(key) || "null");
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    return null;
  }
}
export const debounce = (fn, delay = 250) => {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delay);
  };
};
