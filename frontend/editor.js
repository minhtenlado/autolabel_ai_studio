import {
  $,
  $$,
  api,
  esc,
  icon,
  classes,
  colors,
  basename,
  statusLabel,
  toast,
  empty,
  confirmAction,
  number,
  withBusy,
} from "./api.js";

export function createEditor({ navigate, onChanged }) {
  let image = null,
    annotations = [],
    bitmap = null,
    selected = -1,
    negative = false,
    initial = "",
    undo = [],
    redo = [],
    tool = "select";
  let scale = 1,
    offset = { x: 0, y: 0 },
    drag = null,
    space = false,
    openToken = 0,
    queueToken = 0,
    loading = false;
  let queue = [],
    queueOffset = 0,
    queueTotal = 0,
    queueFilter = "needs_review";
  const PAGE = 30,
    canvas = $("#editorCanvas"),
    stage = $("#canvasStage"),
    context = canvas.getContext("2d"),
    masks = new Map();
  const snapshot = () => JSON.stringify({ annotations, negative });
  const dirty = () => Boolean(image && snapshot() !== initial);
  const visible = () => !$("#review").hidden;
  const point = (e) => {
    const r = canvas.getBoundingClientRect();
    return {
      x: (e.clientX - r.left - offset.x) / scale,
      y: (e.clientY - r.top - offset.y) / scale,
    };
  };
  const clampPoint = (p) => ({
    x: Math.max(0, Math.min(image.width, p.x)),
    y: Math.max(0, Math.min(image.height, p.y)),
  });
  const pushState = () => {
    undo.push(snapshot());
    if (undo.length > 80) undo.shift();
    redo = [];
  };
  function restore(value) {
    const s = JSON.parse(value);
    annotations = s.annotations;
    negative = s.negative;
    selected = -1;
    render();
  }
  async function canLeave() {
    if (!dirty()) return true;
    const discard = await confirmAction({
      title: "Bạn có thay đổi chưa lưu",
      body: "Rời ảnh này sẽ bỏ các chỉnh sửa chưa lưu. Bạn có thể đóng hộp thoại và lưu ảnh trước.",
      confirmText: "Bỏ thay đổi",
      danger: true,
    });
    if (discard) {
      restore(initial);
      undo = [];
      redo = [];
      updateDirty();
    }
    return discard;
  }
  function updateDirty() {
    const badge = $("#dirtyBadge");
    badge.textContent = !image
      ? "Chưa chọn ảnh"
      : dirty()
        ? "Chưa lưu"
        : statusLabel(image.review_state);
    badge.className =
      "pill" +
      (dirty()
        ? " amber"
        : image?.review_state !== "unreviewed" && image
          ? " mint"
          : "");
    $("#negativeImage").checked = negative;
    $$('[data-action="undo"]').forEach(
      (b) => (b.disabled = loading || !undo.length),
    );
    $$('[data-action="redo"]').forEach(
      (b) => (b.disabled = loading || !redo.length),
    );
    $$(
      "[data-ann-class],[data-ann-accepted],[data-ann-delete],[data-ann-sam],#negativeImage",
    ).forEach((control) => {
      control.disabled = !image || loading || image.status === "processing";
    });
    $$(
      '[data-action="save-review"],[data-action="save-next"],[data-action="save-draft"]',
    ).forEach((b) => {
      if (!b.classList.contains("busy"))
        b.disabled = !image || loading || image.status === "processing";
    });
  }
  function fit() {
    if (!bitmap || !visible()) return;
    const rect = stage.getBoundingClientRect();
    scale =
      Math.min(rect.width / image.width, rect.height / image.height) * 0.94;
    offset = {
      x: (rect.width - image.width * scale) / 2,
      y: (rect.height - image.height * scale) / 2,
    };
    draw();
  }
  function resize() {
    const r = stage.getBoundingClientRect(),
      dpr = window.devicePixelRatio || 1;
    if (!r.width || !r.height) return;
    canvas.width = Math.round(r.width * dpr);
    canvas.height = Math.round(r.height * dpr);
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  }
  function drawBox(
    box,
    color,
    label,
    dashed = false,
    highlight = false,
    accepted = true,
  ) {
    const [x1, y1, x2, y2] = box,
      x = offset.x + x1 * scale,
      y = offset.y + y1 * scale,
      w = (x2 - x1) * scale,
      h = (y2 - y1) * scale;
    context.save();
    context.strokeStyle = color;
    context.fillStyle = color + (highlight ? "30" : "12");
    context.lineWidth = highlight ? 2.4 : 1.5;
    if (dashed || !accepted) context.setLineDash([5, 4]);
    if (!dashed) context.fillRect(x, y, w, h);
    context.strokeRect(x, y, w, h);
    context.setLineDash([]);
    if (label) {
      context.font = "11px -apple-system,Segoe UI,sans-serif";
      const tw = context.measureText(label).width + 10,
        ty = Math.max(0, y - 20);
      context.fillStyle = color;
      context.fillRect(Math.max(0, x), ty, tw, 18);
      context.fillStyle = "#0b1825";
      context.fillText(label, Math.max(0, x) + 5, ty + 13);
    }
    if (highlight) {
      for (const [cx, cy] of [
        [x, y],
        [x + w, y],
        [x, y + h],
        [x + w, y + h],
      ]) {
        context.fillStyle = "#fff";
        context.fillRect(cx - 3, cy - 3, 6, 6);
        context.strokeRect(cx - 3, cy - 3, 6, 6);
      }
    }
    context.restore();
  }
  function draw() {
    const dpr = window.devicePixelRatio || 1;
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    context.clearRect(0, 0, canvas.width / dpr, canvas.height / dpr);
    if (!bitmap || !image) return;
    context.drawImage(
      bitmap,
      offset.x,
      offset.y,
      image.width * scale,
      image.height * scale,
    );
    for (const annotation of annotations) {
      const meta = annotation.metadata || {};
      if ($("#layerSam").checked && meta.sam?.mask_path) {
        const key = meta.sam.mask_path;
        if (!masks.has(key)) {
          const mask = new Image();
          masks.set(key, mask);
          mask.onload = draw;
          mask.src = "/api/masks/" + encodeURIComponent(key);
        }
        const mask = masks.get(key);
        if (mask.complete && mask.naturalWidth) {
          context.save();
          context.globalAlpha = 0.25;
          context.drawImage(
            mask,
            offset.x,
            offset.y,
            image.width * scale,
            image.height * scale,
          );
          context.restore();
        }
      }
      if ($("#layerYolo").checked && meta.yolo?.box)
        drawBox(meta.yolo.box, "#74dab1", "YOLO", true);
      if ($("#layerDino").checked && meta.dino?.box)
        drawBox(meta.dino.box, "#81bdf9", "DINO", true);
    }
    if ($("#layerFinal").checked)
      annotations.forEach((a, i) =>
        drawBox(
          a.box,
          colors[a.class_name] || "#ef8080",
          `${i + 1} ${a.class_name}${a.score != null ? " " + Number(a.score).toFixed(2) : ""}`,
          false,
          i === selected,
          a.accepted,
        ),
      );
    $("#zoomLabel").textContent = Math.round(scale * 100) + "%";
  }
  function render() {
    $("#annotationCount").textContent = number(annotations.length);
    $("#annotationList").innerHTML = annotations.length
      ? annotations
          .map(
            (a, i) =>
              `<div class="annotation-row ${i === selected ? "selected" : ""}" data-ann-select="${i}" tabindex="0" role="group" aria-label="Đối tượng ${i + 1}"><div class="annotation-row-top"><span style="background:${colors[a.class_name] || "#ef8080"}"></span><select data-ann-class="${i}" aria-label="Lớp đối tượng ${i + 1}">${[...classes, ...(a.class_name === "ambiguous" ? ["ambiguous"] : [])].map((c) => `<option ${c === a.class_name ? "selected" : ""}>${c}</option>`).join("")}</select><input type="checkbox" data-ann-accepted="${i}" aria-label="Chấp nhận đối tượng ${i + 1}" ${a.accepted ? "checked" : ""}><button class="remove-ann" data-ann-delete="${i}" aria-label="Xóa đối tượng ${i + 1}">×</button></div><div class="annotation-meta"><span>${esc(a.metadata?.original_source || a.source || "manual")}</span><span>${a.quality === "high_risk" ? "Rủi ro cao" : a.reviewed ? "Đã sửa" : a.score != null ? Math.round(a.score * 100) + "% confidence" : "Thủ công"}</span></div>${a.metadata?.agreement === "class_conflict" ? `<p>Khác lớp DINO: ${esc(a.metadata.conflict_class)}</p>` : ""}${a.metadata?.warnings?.length ? `<p>${esc(a.metadata.warnings.join(" · "))}</p>` : ""}${a.metadata?.sam?.mask_derived_box ? `<button class="text-button" data-ann-sam="${i}">Áp dụng box SAM gợi ý</button>` : ""}</div>`,
          )
          .join("")
      : empty(
          "Chưa có đối tượng",
          "Bấm B để vẽ box hoặc xác nhận ảnh không có xe.",
        );
    updateDirty();
    draw();
  }
  async function loadQueue(reset = false) {
    if (reset) queueOffset = 0;
    const token = ++queueToken;
    queueFilter = $("#queueFilter").value;
    const result = await api(
      `/api/images?review=${queueFilter}&limit=${PAGE}&offset=${queueOffset}`,
    );
    if (token !== queueToken) return;
    queue = result.items;
    queueTotal = result.total;
    $("#queueCount").textContent = number(queueTotal);
    $("#queuePage").textContent =
      `${Math.floor(queueOffset / PAGE) + 1}/${Math.max(1, Math.ceil(queueTotal / PAGE))}`;
    $("#queueList").innerHTML = queue.length
      ? queue
          .map(
            (x) =>
              `<button class="queue-item ${x.id === image?.id ? "active" : ""}" data-open-image="${x.id}" title="${esc(x.rel_path)}"><img src="/api/images/${x.id}/thumbnail" loading="lazy" alt=""><span><b>${esc(basename(x.rel_path))}</b><small>${x.object_count} box · ${statusLabel(x.review_state)}</small></span></button>`,
          )
          .join("")
      : empty("Hàng chờ trống", "Thử bộ lọc khác hoặc nhập thêm ảnh.");
    $('[data-action="queue-prev"]').disabled = queueOffset === 0;
    $('[data-action="queue-next"]').disabled = queueOffset + PAGE >= queueTotal;
  }
  async function open(id, { skipGuard = false } = {}) {
    if (!skipGuard && !(await canLeave())) return false;
    const token = ++openToken;
    loading = true;
    updateDirty();
    try {
      const detail = await api("/api/images/" + id),
        nextBitmap = new Image();
      await new Promise((resolve, reject) => {
        nextBitmap.onload = resolve;
        nextBitmap.onerror = () =>
          reject(
            new Error("Không đọc được ảnh nguồn. Kiểm tra tệp trên máy chủ."),
          );
        nextBitmap.src = `/api/images/${id}/file?v=${detail.image.review_version}`;
      });
      if (token !== openToken) return false;
      image = detail.image;
      annotations = detail.annotations.map((a) => ({
        ...a,
        metadata:
          typeof a.metadata === "string"
            ? JSON.parse(a.metadata)
            : a.metadata || {},
        accepted: Boolean(a.accepted),
        box: [a.x1, a.y1, a.x2, a.y2],
      }));
      bitmap = nextBitmap;
      selected = -1;
      negative = image.review_state === "negative";
      undo = [];
      redo = [];
      masks.clear();
      initial = snapshot();
      await navigate("review", { skipGuard: true });
      $("#canvasPlaceholder").hidden = true;
      $("#editorFilename").textContent = basename(image.rel_path);
      $("#editorFilename").title = image.rel_path;
      $("#editorDimensions").textContent =
        `${image.width} × ${image.height} · ${image.camera_id} · ${statusLabel(image.status)} · v${image.review_version}`;
      resize();
      fit();
      render();
      await loadQueue();
      return true;
    } finally {
      if (token === openToken) {
        loading = false;
        updateDirty();
      }
    }
  }
  async function first() {
    await loadQueue(true);
    if (queue.length) await open(queue[0].id);
    else await navigate("review");
  }
  function setTool(value) {
    tool = value;
    $$('[data-action^="tool-"]').forEach((b) => {
      const active = b.dataset.action === "tool-" + tool;
      b.classList.toggle("active", active);
      b.setAttribute("aria-pressed", String(active));
    });
    canvas.style.cursor =
      tool === "pan" ? "grab" : tool === "draw" ? "crosshair" : "default";
  }
  function change(mutator) {
    if (!image || loading) return;
    pushState();
    mutator();
    render();
  }
  async function save(complete = true, next = false) {
    if (!image || loading) return;
    if (negative && annotations.some((a) => a.accepted))
      throw Error(
        "Ảnh không có xe không được giữ box đã chấp nhận. Xóa hoặc bỏ chọn các box trước.",
      );
    if (complete && !annotations.some((a) => a.accepted) && !negative)
      throw Error(
        "Hãy xác nhận “Ảnh không có xe” nếu đã kiểm tra ảnh và không có xe.",
      );
    const index = queue.findIndex((x) => x.id === image.id),
      nextId = queue[index + 1]?.id;
    const id = image.id;
    const payload = {
      expected_version: image.review_version,
      complete,
      negative: complete && negative,
      annotations: annotations.map((a) => ({
        id: a.id ?? null,
        class_name: a.class_name,
        box: a.box,
        accepted: Boolean(a.accepted),
        metadata: a.metadata || {},
      })),
    };
    loading = true;
    updateDirty();
    try {
      await api(`/api/images/${id}/review`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      const updated = await api("/api/images/" + id);
      image = updated.image;
      $("#editorDimensions").textContent =
        `${image.width} × ${image.height} · ${image.camera_id} · ${statusLabel(image.status)} · v${image.review_version}`;
      annotations = updated.annotations.map((a) => ({
        ...a,
        metadata: a.metadata || {},
        accepted: Boolean(a.accepted),
        box: [a.x1, a.y1, a.x2, a.y2],
      }));
      negative = image.review_state === "negative";
      undo = [];
      redo = [];
      initial = snapshot();
      render();
      toast(complete ? "Đã lưu và xác nhận ảnh." : "Đã lưu bản đang sửa.");
      await onChanged();
      if (next) {
        await loadQueue(true);
        const target = nextId || queue.find((x) => x.id !== id)?.id;
        if (target) await open(target, { skipGuard: true });
        else toast("Đã đi hết hàng chờ hiện tại.");
      } else await loadQueue();
    } finally {
      loading = false;
      updateDirty();
    }
  }
  async function step(direction) {
    if (!(await canLeave())) return;
    const index = queue.findIndex((x) => x.id === image?.id);
    let target = queue[index + direction];
    if (index < 0) target = queue[0];
    if (!target && direction > 0 && queueOffset + PAGE < queueTotal) {
      queueOffset += PAGE;
      await loadQueue();
      target = queue[0];
    }
    if (!target && direction < 0 && queueOffset > 0) {
      queueOffset = Math.max(0, queueOffset - PAGE);
      await loadQueue();
      target = queue[queue.length - 1];
    }
    if (target) await open(target.id, { skipGuard: true });
    else toast("Không còn ảnh theo hướng này trong bộ lọc hiện tại.");
  }
  async function history() {
    if (!image) return;
    const result = await api(`/api/images/${image.id}/history`);
    await confirmAction({
      title: "Lịch sử chỉnh sửa",
      body: basename(image.rel_path),
      info: true,
      extra: result.items.length
        ? `<table><thead><tr><th>Thời điểm (UTC)</th><th>Thao tác</th><th>Box</th></tr></thead><tbody>${result.items.map((r) => `<tr><td>${esc(r.created_at)}</td><td>${esc({ create: "Tạo box", update: "Sửa box", delete: "Xóa box", review: "Duyệt ảnh" }[r.action] || r.action)}</td><td>${r.annotation_id || "—"}</td></tr>`).join("")}</tbody></table>`
        : "Chưa có lịch sử chỉnh sửa.",
    });
  }
  $("#annotationList").addEventListener("click", (event) => {
    const remove = event.target.closest("[data-ann-delete]"),
      sam = event.target.closest("[data-ann-sam]");
    if (remove) {
      change(() => {
        annotations.splice(Number(remove.dataset.annDelete), 1);
        selected = -1;
      });
      return;
    }
    if (sam) {
      change(() => {
        const i = Number(sam.dataset.annSam),
          a = annotations[i];
        a.metadata.previous_box = [...a.box];
        a.box = [...a.metadata.sam.mask_derived_box];
        a.accepted = false;
        a.metadata.sam.refinement_applied_at = new Date().toISOString();
        selected = i;
        negative = false;
      });
      return;
    }
    if (event.target.closest("select,input")) return;
    const row = event.target.closest("[data-ann-select]");
    if (row) {
      selected = Number(row.dataset.annSelect);
      render();
    }
  });
  $("#annotationList").addEventListener("change", (event) => {
    if (event.target.matches("[data-ann-class]"))
      change(() => {
        const a = annotations[Number(event.target.dataset.annClass)];
        a.class_name = event.target.value;
        a.class_id = classes.indexOf(a.class_name);
        a.accepted = true;
        negative = false;
      });
    if (event.target.matches("[data-ann-accepted]"))
      change(() => {
        const a = annotations[Number(event.target.dataset.annAccepted)];
        if (a.class_name === "ambiguous" && event.target.checked) {
          toast("Chọn một lớp cụ thể trước khi chấp nhận.", true);
          return;
        }
        a.accepted = event.target.checked;
        if (a.accepted) negative = false;
      });
  });
  $("#negativeImage").addEventListener("change", (event) =>
    change(() => {
      negative = event.target.checked;
    }),
  );
  $("#queueFilter").addEventListener("change", () =>
    loadQueue(true).catch((e) => toast(e.message, true)),
  );
  ["layerFinal", "layerYolo", "layerDino", "layerSam"].forEach((id) =>
    $("#" + id).addEventListener("change", draw),
  );
  canvas.addEventListener("pointerdown", (event) => {
    if (!image || !bitmap || loading || event.button > 1) return;
    if (!$("#layerFinal").checked && tool !== "pan" && !space) {
      toast("Bật lớp Nhãn cuối để chỉnh sửa.", true);
      return;
    }
    event.preventDefault();
    canvas.focus();
    canvas.setPointerCapture(event.pointerId);
    const p = point(event),
      r = canvas.getBoundingClientRect();
    if (tool === "pan" || space || event.button === 1) {
      drag = {
        type: "pan",
        start: { x: event.clientX, y: event.clientY },
        offset: { ...offset },
      };
      return;
    }
    if (p.x < 0 || p.y < 0 || p.x > image.width || p.y > image.height) return;
    const before = snapshot();
    if (tool === "draw") {
      annotations.push({
        class_name: $("#newClass").value,
        source: "manual",
        quality: "human_reviewed",
        accepted: true,
        metadata: {},
        box: [p.x, p.y, p.x, p.y],
      });
      selected = annotations.length - 1;
      drag = { type: "draw", start: p, before, index: selected };
      draw();
      return;
    }
    if (selected >= 0) {
      const box = annotations[selected].box,
        points = [
          [box[0], box[1]],
          [box[2], box[1]],
          [box[0], box[3]],
          [box[2], box[3]],
        ];
      const corner = points.findIndex(
        ([x, y]) => Math.hypot(x - p.x, y - p.y) < 9 / scale,
      );
      if (corner >= 0) {
        drag = {
          type: "resize",
          corner,
          start: p,
          box: [...box],
          before,
          index: selected,
        };
        return;
      }
    }
    const hit = annotations
      .map((a, i) => ({ a, i }))
      .filter(
        ({ a }) =>
          p.x >= a.box[0] &&
          p.x <= a.box[2] &&
          p.y >= a.box[1] &&
          p.y <= a.box[3],
      )
      .sort(
        (a, b) =>
          (a.a.box[2] - a.a.box[0]) * (a.a.box[3] - a.a.box[1]) -
          (b.a.box[2] - b.a.box[0]) * (b.a.box[3] - b.a.box[1]),
      )[0];
    selected = hit ? hit.i : -1;
    if (hit)
      drag = {
        type: "move",
        start: p,
        box: [...hit.a.box],
        before,
        index: selected,
      };
    render();
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!drag || !image) return;
    if (drag.type === "pan") {
      offset = {
        x: drag.offset.x + event.clientX - drag.start.x,
        y: drag.offset.y + event.clientY - drag.start.y,
      };
      draw();
      return;
    }
    const p = clampPoint(point(event)),
      a = annotations[drag.index];
    if (!a) return;
    if (drag.type === "draw")
      a.box = [
        Math.min(p.x, drag.start.x),
        Math.min(p.y, drag.start.y),
        Math.max(p.x, drag.start.x),
        Math.max(p.y, drag.start.y),
      ];
    if (drag.type === "move") {
      const b = drag.box,
        dx = Math.max(-b[0], Math.min(image.width - b[2], p.x - drag.start.x)),
        dy = Math.max(-b[1], Math.min(image.height - b[3], p.y - drag.start.y));
      a.box = [b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy];
    }
    if (drag.type === "resize") {
      const b = drag.box,
        opposite = [
          [b[2], b[3]],
          [b[0], b[3]],
          [b[2], b[1]],
          [b[0], b[1]],
        ][drag.corner];
      a.box = [
        Math.min(p.x, opposite[0]),
        Math.min(p.y, opposite[1]),
        Math.max(p.x, opposite[0]),
        Math.max(p.y, opposite[1]),
      ];
    }
    draw();
  });
  function endDrag(event) {
    if (!drag) return;
    const current = drag;
    drag = null;
    if (current.type === "pan") return;
    const a = annotations[current.index];
    if (
      !a ||
      a.box[2] - a.box[0] < 1 ||
      a.box[3] - a.box[1] < 1 ||
      event.type === "pointercancel"
    ) {
      restore(current.before);
      return;
    }
    if (snapshot() !== current.before) {
      undo.push(current.before);
      if (undo.length > 80) undo.shift();
      redo = [];
      negative = false;
    }
    render();
  }
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);
  canvas.addEventListener(
    "wheel",
    (event) => {
      if (!image) return;
      event.preventDefault();
      const anchor = point(event),
        r = canvas.getBoundingClientRect();
      scale = Math.max(
        0.01,
        Math.min(25, scale * (event.deltaY < 0 ? 1.12 : 1 / 1.12)),
      );
      offset = {
        x: event.clientX - r.left - anchor.x * scale,
        y: event.clientY - r.top - anchor.y * scale,
      };
      draw();
    },
    { passive: false },
  );
  canvas.addEventListener("contextmenu", (event) => event.preventDefault());
  window.addEventListener("beforeunload", (event) => {
    if (dirty()) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  window.addEventListener("keyup", (event) => {
    if (event.code === "Space") space = false;
  });
  window.addEventListener("blur", () => {
    space = false;
  });
  window.addEventListener("keydown", (event) => {
    if (!visible() || $("#confirmDialog").open) return;
    const ctrl = event.ctrlKey || event.metaKey,
      key = event.key.toLowerCase();
    if (ctrl && key === "s") {
      event.preventDefault();
      save(true).catch((e) => toast(e.message, true));
      return;
    }
    if (event.target.closest('input,textarea,select,[contenteditable="true"]'))
      return;
    if (event.code === "Space") {
      event.preventDefault();
      space = true;
      return;
    }
    if (ctrl && key === "z") {
      event.preventDefault();
      actions[event.shiftKey ? "redo" : "undo"]();
      return;
    }
    if (ctrl && key === "y") {
      event.preventDefault();
      actions.redo();
      return;
    }
    if (ctrl || event.altKey) return;
    if (key === "b") setTool("draw");
    if (key === "v") setTool("select");
    if (key === "f") fit();
    if ((key === "delete" || key === "backspace") && selected >= 0) {
      event.preventDefault();
      actions["delete-selected"]();
    }
    if (key === "arrowright" || key === "arrowleft") {
      event.preventDefault();
      step(key === "arrowright" ? 1 : -1).catch((e) => toast(e.message, true));
    }
    if (/^[1-5]$/.test(key) && selected >= 0)
      change(() => {
        annotations[selected].class_name = classes[Number(key) - 1];
        annotations[selected].accepted = true;
        negative = false;
      });
  });
  new ResizeObserver(() => {
    resize();
  }).observe(stage);
  const actions = {
    "tool-select": () => setTool("select"),
    "tool-draw": () => setTool("draw"),
    "tool-pan": () => setTool("pan"),
    fit,
    undo: () => {
      if (!undo.length) return;
      redo.push(snapshot());
      restore(undo.pop());
    },
    redo: () => {
      if (!redo.length) return;
      undo.push(snapshot());
      restore(redo.pop());
    },
    "delete-selected": () => {
      if (selected >= 0)
        change(() => {
          annotations.splice(selected, 1);
          selected = -1;
        });
    },
    "accept-all": () =>
      change(() => {
        annotations.forEach((a) => {
          a.accepted = classes.includes(a.class_name);
        });
        negative = false;
      }),
    "save-review": () => save(true),
    "save-draft": () => save(false),
    "save-next": () => save(true, true),
    "editor-prev": () => step(-1),
    "editor-next": () => step(1),
    "editor-reload": () => (image ? open(image.id) : first()),
    history,
    "queue-prev": async () => {
      queueOffset = Math.max(0, queueOffset - PAGE);
      await loadQueue();
    },
    "queue-next": async () => {
      if (queueOffset + PAGE < queueTotal) {
        queueOffset += PAGE;
        await loadQueue();
      }
    },
  };
  return {
    actions,
    open,
    first,
    loadQueue,
    dirty,
    canLeave,
    fit,
    resize,
    clear() {
      image = null;
      annotations = [];
      bitmap = null;
      initial = "";
      undo = [];
      redo = [];
      $("#canvasPlaceholder").hidden = false;
      $("#editorFilename").textContent = "Chọn ảnh từ hàng chờ";
      $("#editorDimensions").textContent = "Vẽ, chỉnh sửa và xác nhận từng box";
      render();
      resize();
    },
  };
}
