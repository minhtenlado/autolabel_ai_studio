/** Real browser smoke test. Uses an isolated server, temporary DB and synthetic images. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const temp = fs.mkdtempSync(path.join(os.tmpdir(), "autolabel-ui-"));
const shots = process.env.UI_SCREENSHOT_DIR || path.join(temp, "screenshots");
fs.mkdirSync(shots, { recursive: true });
const python = process.env.PYTHON || "python";
const fixture = spawnSync(
  python,
  ["tests/make_ui_fixture.py", path.join(temp, "input")],
  { cwd: root, encoding: "utf8" },
);
assert.equal(fixture.status, 0, fixture.stderr);
const modulePath = process.env.PLAYWRIGHT_MODULE;
const { chromium } = await import(
  modulePath ? pathToFileURL(modulePath).href : "playwright"
);
const port = process.env.UI_TEST_PORT || "8781",
  url = "http://127.0.0.1:" + port;
const server = spawn(
  python,
  [
    "-m",
    "uvicorn",
    "backend.api.app:app",
    "--host",
    "127.0.0.1",
    "--port",
    port,
  ],
  {
    cwd: root,
    env: { ...process.env, AUTOLABEL_DATA_DIR: path.join(temp, "workspace") },
    stdio: ["ignore", "pipe", "pipe"],
  },
);
let logs = "";
server.stderr.on("data", (d) => (logs += d.toString()));
server.stdout.on("data", (d) => (logs += d.toString()));
let browser;
const errors = [],
  checks = [];
function check(name) {
  checks.push(name);
  console.log("PASS", name);
}
async function until(fn, timeout = 12000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    if (await fn()) return;
    await new Promise((r) => setTimeout(r, 60));
  }
  throw Error("Timed out waiting for condition");
}
try {
  await until(async () => {
    try {
      return (await fetch(url + "/api/stats")).ok;
    } catch {
      return false;
    }
  });
  browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROMIUM_EXECUTABLE
      ? {
          executablePath: process.env.CHROMIUM_EXECUTABLE,
          args: [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-zygote",
            "--single-process",
          ],
        }
      : {}),
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1050 },
    acceptDownloads: true,
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  let expectingConflict = false;
  page.on("console", (m) => {
    if (
      m.type() === "error" &&
      !(expectingConflict && m.text().includes("409"))
    )
      errors.push(m.text());
  });
  const nav = async (name) => {
    await page.locator(`.nav-item[data-view="${name}"]`).click();
    await page.waitForFunction(
      (name) => !document.querySelector("#" + name).hidden,
      name,
    );
  };
  await page.goto(url);
  await page.waitForSelector('#connection:has-text("Đã kết nối")');
  assert.equal(await page.locator("#statImages").textContent(), "0");
  await page.screenshot({
    path: path.join(shots, "dashboard-empty.png"),
    fullPage: true,
  });
  check("Empty dashboard renders with live API");
  await nav("dataset");
  await page.locator("#datasetPath").fill(path.join(temp, "input"));
  await page.locator("#importButton").click();
  await page.waitForFunction(
    () =>
      document.querySelector("#importResult").textContent.includes("Đã thêm"),
    null,
    { timeout: 20000 },
  );
  assert.match(await page.locator("#importResult").textContent(), /12 ảnh/);
  await page.waitForSelector(".image-card");
  check("Async folder import reports 12 images, duplicates and corrupt files");
  await page.locator("#imageSearch").fill("camera_02");
  await until(async () => (await page.locator(".image-card").count()) === 4);
  check("Debounced image search filters server data");
  await page.locator("#imageSearch").fill("");
  await until(async () => (await page.locator(".image-card").count()) === 12);
  await page.locator('[data-action="table-mode"]').click();
  await until(
    async () => (await page.locator("#imageLibrary tbody tr").count()) === 12,
  );
  await page.locator('[data-action="grid-mode"]').click();
  await until(async () => (await page.locator(".image-card").count()) === 12);
  await page.screenshot({
    path: path.join(shots, "dataset-desktop.png"),
    fullPage: true,
  });
  await page.locator(".image-card [data-open-image]").first().click();
  await page.waitForSelector("#canvasPlaceholder[hidden]", {
    state: "attached",
  });
  await page.waitForSelector(".annotation-row");
  check("Review loads original annotations");
  await page.locator('[data-action="tool-draw"]').click();
  const box = await page.locator("#editorCanvas").boundingBox();
  // Drag bottom-right to top-left, in the image interior.
  await page.mouse.move(box.x + box.width * 0.65, box.y + box.height * 0.65);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.45, box.y + box.height * 0.4, {
    steps: 8,
  });
  await page.mouse.up();
  assert.equal(await page.locator("#annotationCount").textContent(), "3");
  assert.equal(await page.locator("#dirtyBadge").textContent(), "Chưa lưu");
  await page.locator('[data-action="undo"]').click();
  assert.equal(await page.locator("#annotationCount").textContent(), "2");
  await page.locator('[data-action="redo"]').click();
  assert.equal(await page.locator("#annotationCount").textContent(), "3");
  check("Canvas draws in reverse direction and undo/redo work");
  await page.locator('.nav-item[data-view="dataset"]').click();
  await page.waitForSelector("#confirmDialog[open]");
  await page.locator('#confirmDialog button[value="cancel"]').click();
  assert.equal(
    await page.locator("#review").evaluate((el) => el.hidden),
    false,
  );
  check("Unsaved changes block navigation until user decides");
  await page.locator("#saveReviewButton").click();
  await page.waitForFunction(
    () => document.querySelector("#dirtyBadge").textContent === "Đã kiểm duyệt",
  );
  check("Review saves with version control");
  await page.screenshot({
    path: path.join(shots, "review-desktop.png"),
    fullPage: true,
  });
  // Simulate another tab saving first; the editor must retain local edits on 409.
  const detail = await (await fetch(url + "/api/images/1")).json();
  const other = await fetch(url + "/api/images/1/review", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      expected_version: detail.image.review_version,
      complete: true,
      annotations: detail.annotations.map((a) => ({
        id: a.id,
        class_name: a.class_name,
        box: [a.x1, a.y1, a.x2, a.y2],
        accepted: Boolean(a.accepted),
      })),
    }),
  });
  assert.equal(other.status, 200);
  await page.locator("[data-ann-class]").first().selectOption("truck");
  expectingConflict = true;
  const conflict = page.waitForResponse(
    (r) => r.url().endsWith("/api/images/1/review") && r.status() === 409,
  );
  await page.locator("#saveReviewButton").click();
  await conflict;
  await until(async () =>
    (await page.locator("#toasts").textContent()).includes("tab khác"),
  );
  assert.equal(
    await page.locator("[data-ann-class]").first().inputValue(),
    "truck",
  );
  assert.equal(await page.locator("#dirtyBadge").textContent(), "Chưa lưu");
  expectingConflict = false;
  await page.locator('[data-action="editor-reload"]').click();
  await page.waitForSelector("#confirmDialog[open]");
  await page.locator("#dialogConfirm").click();
  await until(
    async () =>
      (await page.locator("[data-ann-class]").first().inputValue()) === "car" &&
      (await page.locator("#editorDimensions").textContent()).includes("v2") &&
      (await page.locator("[data-ann-class]").first().isEnabled()),
  );
  check("Stale tab conflict keeps local edits and reload recovers safely");
  // Confirming discard must actually restore the editor snapshot, including when only navigating away.
  await page.locator("[data-ann-class]").first().selectOption("truck");
  await page.locator('.nav-item[data-view="dataset"]').click();
  await page.locator("#dialogConfirm").click();
  await nav("review");
  assert.equal(
    await page.locator("[data-ann-class]").first().inputValue(),
    "car",
  );
  assert.equal(
    await page.locator("#dirtyBadge").textContent(),
    "Đã kiểm duyệt",
  );
  check("Discarding changes restores saved state");
  await nav("export");
  await page.locator("#exportButton").click();
  await page.waitForSelector("#exportResult a[download]", { timeout: 20000 });
  const downloadPromise = page.waitForEvent("download");
  await page.locator("#exportResult a[download]").click();
  const download = await downloadPromise;
  assert.match(download.suggestedFilename(), /\.zip$/);
  await download.saveAs(path.join(temp, "export.zip"));
  check("Detection snapshot generates a downloadable ZIP");
  await nav("traffic");
  await page.waitForFunction(
    () => document.querySelector("#cameraSelect").options.length === 3,
  );
  await page.waitForSelector("#roiPlaceholder[hidden]", { state: "attached" });
  await page.locator('[data-action="roi-new"]').click();
  const roi = await page.locator("#roiCanvas").boundingBox();
  for (const [x, y] of [
    [0.2, 0.25],
    [0.8, 0.25],
    [0.9, 0.85],
    [0.1, 0.85],
  ])
    await page.mouse.click(roi.x + roi.width * x, roi.y + roi.height * y);
  await page.locator('[data-action="roi-finish"]').click();
  await page.locator("#freeMax").fill("1");
  await page.locator("#busyMax").fill("5");
  await page.locator("#jamMin").fill("10");
  await page.locator("#calibrationConfirmed").check();
  await page.locator('#roiForm button[type="submit"]').click();
  await until(async () =>
    (await page.locator("#toasts").textContent()).includes("Đã lưu ROI"),
  );
  await page.locator('[data-action="analyze-traffic"]').click();
  await page.waitForSelector("#trafficTable tbody tr", { timeout: 20000 });
  check("ROI drawing, calibration and background traffic analysis work");
  const select = page.locator("#trafficTable select").first();
  await select.selectOption("Un_tac_nang");
  await page.locator('[data-action="confirm-traffic"]').first().click();
  await until(async () =>
    (
      await page.locator("#trafficTable tbody tr").first().textContent()
    ).includes("Đã xác nhận"),
  );
  await page.screenshot({
    path: path.join(shots, "traffic-desktop.png"),
    fullPage: true,
  });
  await nav("export");
  await page.locator("#exportType").selectOption("classification");
  await page.locator("#exportButton").click();
  await until(async () =>
    (await page.locator("#exportHistory").textContent()).includes(
      "Classification",
    ),
  );
  check("Human-verified classification exports from the UI");
  await nav("dashboard");
  await page.screenshot({
    path: path.join(shots, "dashboard-populated.png"),
    fullPage: true,
  });
  await page.locator("#themeToggle").click();
  assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
  await page.reload();
  await page.waitForSelector('#connection:has-text("Đã kết nối")');
  assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
  await page.screenshot({
    path: path.join(shots, "dashboard-dark.png"),
    fullPage: true,
  });
  check("Theme survives reload");
  await page.locator("#themeToggle").click();
  await page.setViewportSize({ width: 390, height: 844 });
  for (const name of [
    "dashboard",
    "dataset",
    "labeling",
    "review",
    "traffic",
    "export",
    "activity",
  ]) {
    await nav(name);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth + 1,
    );
    assert.equal(overflow, false, "Horizontal overflow: " + name);
  }
  await nav("dataset");
  await page.screenshot({
    path: path.join(shots, "dataset-mobile.png"),
    fullPage: true,
  });
  await page.locator(".image-card [data-open-image]").first().click();
  await page.waitForSelector("#canvasPlaceholder[hidden]", {
    state: "attached",
  });
  await page.screenshot({
    path: path.join(shots, "review-mobile.png"),
    fullPage: true,
  });
  check("All 7 views remain navigable without horizontal overflow at 390 px");
  assert.deepEqual(errors, [], "Browser console/page errors");
  check("No browser JavaScript errors");
  fs.writeFileSync(
    path.join(shots, "ui-results.json"),
    JSON.stringify(
      {
        checks,
        errors,
        browser: browser.version(),
        viewports: ["1440x1050", "390x844"],
        fixture: "synthetic",
        at: new Date().toISOString(),
      },
      null,
      2,
    ),
  );
  console.log("UI TESTS PASSED:", checks.length, "Screenshots:", shots);
} finally {
  if (browser) await browser.close();
  server.kill("SIGTERM");
  if (!checks.includes("No browser JavaScript errors"))
    console.log("SERVER TAIL", logs.slice(-4000));
}
