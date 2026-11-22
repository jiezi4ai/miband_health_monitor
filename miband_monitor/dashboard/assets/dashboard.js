"use strict";

// Optional WEB_TOKEN: when the server requires one, it is passed as ?token=
// in the page URL and forwarded to every API/SSE request.
const _pageToken = new URLSearchParams(location.search).get("token") || "";
const _withToken = (url) =>
  _pageToken ? url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(_pageToken) : url;

const MAX_POINTS = 300;                       // points kept per chart in the browser
const HISTORY_LIMIT = 300;                    // persisted rows requested on load
const KINDS = ["heart_rate", "spo2", "steps", "imu"];
// Battery is a device event series (B-14): it lives in the hub's snapshot and
// SSE stream but has no SQLite history table, so it is not part of KINDS.
const series = { heart_rate: [], spo2: [], steps: [], imu: [], battery: [] };
// Persisted rows are kept apart from the live buffer so every snapshot (the
// initial fetch AND the first SSE frame) can merge them back without losing
// history or duplicating points.
const dbSeries = { heart_rate: [], spo2: [], steps: [], imu: [] };
const latest = {};
let messageCount = 0;
let renderQueued = false;

const el = (id) => document.getElementById(id);

function fmt(value, digits) {
  if (value === undefined || value === null || Number.isNaN(value)) return "--";
  return Number(value).toFixed(digits === undefined ? 0 : digits);
}

function setText(id, text) { const node = el(id); if (node) node.textContent = text; }

function applyLatest(kind, record) {
  latest[kind] = record;
  if (kind === "heart_rate") setText("hr", fmt(record.bpm));
  if (kind === "spo2") setText("spo2", fmt(record.spo2));
  if (kind === "battery") setText("battery", fmt(record.level));
  if (kind === "steps") {
    setText("steps", fmt(record.steps));
    setText("dist", fmt(record.distance_m));
    setText("cal", fmt(record.calories));
  }
  if (kind === "imu") setText("imu", fmt(record.magnitude_g, 2));
  setText("updated", new Date().toLocaleTimeString());
}

function applyDevice(record) {
  const labels = {
    not_connected: "未连接", connecting: "连接中", connected: "已连接",
    initializing: "初始化中", initialized: "就绪"
  };
  const node = el("deviceState");
  if (!node) return;
  node.classList.remove("hidden");
  const task = record && record.busy_task ? " · " + record.busy_task : "";
  const reconnects = record && record.reconnect_count
    ? " · 重连 " + record.reconnect_count + " 次" : "";
  node.textContent = "设备：" + (labels[(record || {}).state] || (record || {}).state || "--")
    + task + reconnects;
}

function scheduleRender() {
  if (renderQueued) return;
  renderQueued = true;
  window.requestAnimationFrame(() => { renderQueued = false; renderAll(); });
}

function drawChart(canvasId, data, key, color, options) {
  const canvas = el(canvasId);
  if (!canvas) return;
  options = options || {};
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || 320;
  const height = canvas.clientHeight || 140;
  const pixelW = Math.round(width * dpr);
  const pixelH = Math.round(height * dpr);
  if (canvas.width !== pixelW || canvas.height !== pixelH) {
    canvas.width = pixelW;
    canvas.height = pixelH;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const pad = { left: 36, right: 8, top: 8, bottom: 18 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  ctx.strokeStyle = "#2a323c";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i <= 3; i++) {
    const y = pad.top + plotH * i / 3;
    ctx.moveTo(pad.left, y);
    ctx.lineTo(pad.left + plotW, y);
  }
  ctx.stroke();

  const values = data.map((row) => row[key]).filter((v) => typeof v === "number");
  if (values.length < 2) {
    ctx.fillStyle = "#8b98a5";
    ctx.font = "12px sans-serif";
    ctx.fillText("等待数据…", pad.left + 8, pad.top + plotH / 2);
    return;
  }

  let lo = Math.min.apply(null, values);
  let hi = Math.max.apply(null, values);
  if (options.min !== undefined) lo = Math.min(lo, options.min);
  if (options.max !== undefined) hi = Math.max(hi, options.max);
  const span = (hi - lo) || 1;
  const x = (index) => pad.left + plotW * index / (data.length - 1);
  const y = (value) => pad.top + plotH * (1 - (value - lo) / span);

  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.beginPath();
  let started = false;
  data.forEach((row, index) => {
    const value = row[key];
    if (typeof value !== "number") return;
    const px = x(index);
    const py = y(value);
    if (!started) { ctx.moveTo(px, py); started = true; } else { ctx.lineTo(px, py); }
  });
  ctx.stroke();

  ctx.fillStyle = "#8b98a5";
  ctx.font = "10px sans-serif";
  ctx.fillText(String(Math.round(hi)), 2, pad.top + 8);
  ctx.fillText(String(Math.round(lo)), 2, pad.top + plotH);
}

function renderAll() {
  drawChart("hrChart", series.heart_rate, "bpm", "#ff5c7a", { min: 40, max: 180 });
  drawChart("spo2Chart", series.spo2, "spo2", "#38bdf8", { min: 85, max: 100 });
  drawChart("batteryChart", series.battery, "level", "#fbbf24", { min: 0, max: 100 });
  drawChart("stepsChart", series.steps, "steps", "#4ade80", { min: 0 });
  drawChart("imuChart", series.imu, "magnitude_g", "#fbbf24", { min: 0 });

  const hrValues = series.heart_rate.map((row) => row.bpm).filter((v) => typeof v === "number");
  setText("hrRange", hrValues.length ? Math.min.apply(null, hrValues) + "–" +
          Math.max.apply(null, hrValues) + " BPM" : "");
  const spo2Values = series.spo2.map((row) => row.spo2).filter((v) => typeof v === "number");
  setText("spo2Range", spo2Values.length ? Math.min.apply(null, spo2Values) + "–" +
          Math.max.apply(null, spo2Values) + " %" : "");
  const batteryValues = series.battery.map((row) => row.level).filter((v) => typeof v === "number");
  setText("batteryRange", batteryValues.length ? Math.min.apply(null, batteryValues) + "–" +
          Math.max.apply(null, batteryValues) + " %" : "");
  const stepValues = series.steps.map((row) => row.steps).filter((v) => typeof v === "number");
  setText("stepsRange", stepValues.length ? "总计 " + stepValues[stepValues.length - 1] : "");
  const imuValues = series.imu.map((row) => row.magnitude_g).filter((v) => typeof v === "number");
  setText("imuRange", imuValues.length ? "max " + Math.max.apply(null, imuValues).toFixed(2) + " g" : "");
}

function applyRecord(record) {
  const kind = record.kind;
  if (kind === "gui_state" && record.gui) {
    if (window.MiBandGui) window.MiBandGui.applyGuiState(record.gui);
    return;
  }
  if (kind === "gui_log" && record.entry) {
    if (window.MiBandGui) window.MiBandGui.appendLogLine(record.entry);
    return;
  }
  if (kind === "playbook_result" && record.result) {
    if (window.MiBandGui) window.MiBandGui.renderPlaybookOutput(record.result);
    return;
  }
  if (kind === "workout" && record.workout) {
    if (window.MiBandWorkout) window.MiBandWorkout.applyWorkout(record.workout, series, MAX_POINTS);
    messageCount += 1;
    setText("events", String(messageCount));
    scheduleRender();
    return;
  }
  if (kind === "device") {
    applyDevice(record);
    messageCount += 1;
    setText("events", String(messageCount));
    return;
  }
  if (!series[kind]) return;
  const rows = series[kind];
  if (rows.length && record.ts < rows[rows.length - 1].ts) {
    // A late frame (e.g. a band-side timestamp arriving after live samples)
    // must not corrupt the chronological order of the chart.
    let index = rows.length - 1;
    while (index >= 0 && rows[index].ts > record.ts) index -= 1;
    rows.splice(index + 1, 0, record);
  } else {
    rows.push(record);
  }
  if (rows.length > MAX_POINTS) rows.shift();
  if (rows[rows.length - 1] === record) applyLatest(kind, record);
  messageCount += 1;
  setText("events", String(messageCount));
  scheduleRender();
}

function mergeRows(historyRows, liveRows) {
  const byTs = new Map();
  (historyRows || []).forEach((row) => byTs.set(row.ts, row));
  // Live rows win on a timestamp collision: they are the freshest reading.
  (liveRows || []).forEach((row) => byTs.set(row.ts, row));
  return Array.from(byTs.values()).sort((a, b) => a.ts - b.ts).slice(-MAX_POINTS);
}

function loadDbHistory() {
  return Promise.all(KINDS.map((kind) =>
    fetch(_withToken("/api/history?kind=" + encodeURIComponent(kind) +
          "&source=db&limit=" + HISTORY_LIMIT))
      .then((response) => response.ok ? response.json() : null)
      .then((payload) => {
        if (payload && Array.isArray(payload.rows)) dbSeries[kind] = payload.rows;
      })
      .catch(() => {})   // no provider / no database yet -> live-only view
  )).then(() => {
    const total = KINDS.reduce((sum, kind) => sum + dbSeries[kind].length, 0);
    setText("historyNote", total ? " · 含 " + total + " 条数据库历史" : "");
  });
}

function applySnapshot(snapshot) {
  if (!snapshot || !snapshot.series) return;
  for (const kind of KINDS) {
    series[kind] = mergeRows(dbSeries[kind], snapshot.series[kind] || []);
    const rows = series[kind];
    if (rows.length) applyLatest(kind, rows[rows.length - 1]);
  }
  // Battery has no DB history table; take the hub series directly.
  series.battery = mergeRows([], snapshot.series.battery || []);
  if (series.battery.length) applyLatest("battery", series.battery[series.battery.length - 1]);
  const device = snapshot.event_latest && snapshot.event_latest.device;
  if (device) applyDevice(device);
  if (snapshot.workout && window.MiBandWorkout) {
    window.MiBandWorkout.applyWorkout(snapshot.workout, series, MAX_POINTS);
  }
  if (snapshot.gui && window.MiBandGui) {
    window.MiBandGui.applyGuiState(snapshot.gui);
  }
  setText("events", String(snapshot.events_sent || 0));
  messageCount = snapshot.events_sent || 0;
  scheduleRender();
}

function setStatus(text, state) {
  setText("statusText", text);
  const dot = el("dot");
  if (!dot) return;
  dot.className = "dot" + (state ? " " + state : "");
}

function connectEvents() {
  const source = new EventSource(_withToken("/events"));
  source.onopen = () => setStatus("实时连接", "on");
  source.onerror = () => setStatus("连接中断，自动重连…", "err");
  source.onmessage = (event) => {
    let payload;
    try { payload = JSON.parse(event.data); } catch (err) { return; }
    if (payload.type === "snapshot") {
      applySnapshot(payload);
    } else {
      applyRecord(payload);
    }
  };
}

// Load persisted rows BEFORE opening SSE: the stream's first frame is itself a
// snapshot, and applying it earlier would wipe the history we just fetched.
Promise.all([
  fetch(_withToken("/api/snapshot")).then((response) => response.json()).catch(() => null),
  loadDbHistory(),
]).then(([snapshot]) => {
  applySnapshot(snapshot);
  connectEvents();
});
window.addEventListener("resize", scheduleRender);
