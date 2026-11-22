"use strict";

(function () {
  const STEP_META = {
    preflight: ["1. 前置自检与配置校验", "检查凭据、蓝牙适配器状态与输出目录"],
    discovering: ["2. 直连 / 等待广播脉冲", "无手机链路时每 40–60s 发一次脉冲，请保持手机蓝牙关闭"],
    resolving_gatt: ["3. GATT 服务解析与配对", "首次建链需约 4–10s 解析服务表，建议点亮手环屏幕"],
    authenticating: ["4. ECDH 安全认证", "正在完成华米分片密钥挑战响应"],
    streaming: ["5. 实时健康数据采集中", "心率、步数与传感器流已建立"],
  };
  const PLAYBOOK_ZH = {
    doctor_check: ["环境与蓝牙基线自检", "只读检查 .env 权限、ECDH 后端、适配器电源与 BlueZ 配对状态"],
    probe_radio_scan: ["只扫不连射频探针 (15s)", "安全监听空口广播包（绝不 Connect），区分手环静默与适配器假死"],
    clear_ghost_link: ["清理 BlueZ 幽灵连接", "安全断开残留 Connected=True 链路（无残留时自动跳过）"],
    trust_and_pairable: ["标记 Trusted 并开启配对", "设置 Trusted=True 保留 GATT 缓存并启用内核自动回连"],
    reset_stale_bond: ["清除陈旧 LTK 并准备重配", "解决约 5 秒 ServicesResolved=False 掉线，下轮自动启用配对 Agent"],
    power_on_adapter: ["唤醒蓝牙适配器电源", "开启 Linux 蓝牙控制器电源 (Powered=True)"],
    fix_env_permissions: ["收紧 .env 凭据权限 (0600)", "确保密钥文件仅当前用户可读写"],
    disable_usb_autosuspend: ["关闭 USB 蓝牙自动休眠", "防止长时采集期间系统挂起蓝牙 USB 控制器"],
    usb_reset_adapter: ["USB 复位适配器并重启服务", "恢复 BARROT 等 USB 适配器 0 包假死 (-112 / EHOSTDOWN)"],
  };

  let userToggledCenter = false;
  const _pageToken = new URLSearchParams(location.search).get("token") || "";
  const _withToken = (url) =>
    _pageToken ? url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(_pageToken) : url;
  const gEl = (id) => document.getElementById(id);
  const mk = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };

  async function apiJson(url, method, body) {
    const opts = { method: method || "GET", headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const resp = await fetch(_withToken(url), opts);
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || "请求失败 (" + resp.status + ")");
    return data;
  }

  function showToast(text, level) {
    const box = gEl("guiBanner");
    if (!box) return;
    box.textContent = text || "";
    box.className = "gui-pill " + (level || "");
    box.classList.toggle("hidden", !text);
  }

  function renderSteps(gui) {
    const wrap = gEl("guiSteps");
    if (!wrap) return;
    wrap.textContent = "";
    (gui.steps || []).forEach((s) => {
      const [title, desc] = STEP_META[s.id] || [s.id, ""];
      const row = mk("div", "gui-step " + s.state);
      const txt = mk("div");
      const strong = mk("div", "", title);
      strong.style.fontWeight = "600";
      const sub = mk("div", "", desc);
      sub.style.cssText = "color:#8b98a5;font-size:11px";
      txt.append(strong, sub);
      row.append(mk("span", "gui-step-dot"), txt);
      wrap.appendChild(row);
    });
  }

  function renderTips(gui) {
    const list = gEl("guiTips");
    if (!list) return;
    const tips = [];
    if (!gui.config || !gui.config.device_id_configured || !gui.config.auth_key_valid) {
      tips.push("尚未完成 DEVICE_ID / AUTH_KEY 配置：请先点击顶部「凭据设置」或选择「模拟手环 (Demo)」体验。");
    }
    if (gui.phase === "discovering" || gui.phase === "reconnecting" || gui.phase === "idle") {
      tips.push("请关闭手机蓝牙（或开启飞行模式），并确认手环近期曾在 Zepp Life 中开启广播。");
      tips.push("手环在无手机链路时每 40–60 秒才发 1 个广播脉冲，滑屏不会加速，请耐心等待。");
    }
    if (gui.phase === "resolving_gatt") {
      tips.push("正在解析 GATT 服务表：首次建链约需 4–9 秒，请保持手环靠近适配器并点亮屏幕。");
    }
    if (gui.phase === "error") {
      tips.push("连接遇到异常：请优先尝试右侧高亮的「一键修复剧本」，或点击「环境自检」排查。");
    }
    if (gui.phase === "streaming") {
      tips.push("连接已稳定！健康数据正实时写入本地存储并推送至下方看板。");
    }
    list.textContent = "";
    tips.forEach((t) => list.appendChild(mk("li", "", t)));
  }

  function renderPlaybooks(gui) {
    const wrap = gEl("guiPlaybooks");
    if (!wrap) return;
    const recs = new Set(gui.recommended_playbooks || []);
    const specs = (gui.playbooks || []).slice().sort((a, b) => Number(recs.has(b.id)) - Number(recs.has(a.id)));
    wrap.textContent = "";
    specs.forEach((spec) => {
      const isRec = recs.has(spec.id);
      const card = mk("div", "gui-pb" + (isRec ? " rec" : ""));
      const info = mk("div");
      const zh = PLAYBOOK_ZH[spec.id];
      info.append(
        mk("div", "gui-pb-title", (isRec ? "[推荐] " : "") + (zh ? zh[0] : spec.title)),
        mk("div", "gui-pb-desc", zh ? zh[1] : spec.summary)
      );
      const btn = mk("button", "gui-btn sm" + (isRec ? " warn" : ""), "一键执行");
      btn.onclick = () => runPlaybook(spec.id, btn);
      card.append(info, btn);
      wrap.appendChild(card);
    });
  }

  function renderPlaybookOutput(res) {
    const summaryEl = gEl("guiPbSummary");
    const cmdBox = gEl("guiCmdBox");
    const cmdCode = gEl("guiCmdText");
    if (!res || !summaryEl) return;
    summaryEl.classList.remove("hidden");
    const details = res.details && res.details.length ? "\n" + res.details.join("\n") : "";
    summaryEl.textContent = "[" + String(res.status || "").toUpperCase() + "] " + (res.summary || "") + details;
    if (cmdBox && cmdCode) {
      cmdBox.classList.toggle("hidden", !res.manual_command);
      cmdCode.textContent = res.manual_command || "";
    }
  }

  function appendLogLine(entry) {
    const box = gEl("guiLogs");
    if (!box || !entry) return;
    const timeStr = new Date((entry.ts || 0) * 1000).toLocaleTimeString();
    box.appendChild(mk("div", "gui-log-line " + (entry.level || ""), "[" + timeStr + "] " + entry.level + " " + entry.message));
    while (box.children.length > 100) box.removeChild(box.firstChild);
    box.scrollTop = box.scrollHeight;
  }

  function applyGuiState(gui) {
    if (!gui) return;
    if (gEl("guiToolbar")) gEl("guiToolbar").classList.remove("hidden");
    if (gEl("guiConnectBtn")) gEl("guiConnectBtn").disabled = Boolean(gui.running);
    if (gEl("guiStopBtn")) gEl("guiStopBtn").disabled = !gui.running;
    if (gEl("guiScanBtn")) gEl("guiScanBtn").disabled = Boolean(gui.running);

    const phaseEl = gEl("guiPhaseBadge");
    if (phaseEl) {
      phaseEl.textContent = gui.status_message || gui.phase;
      phaseEl.className = "gui-pill " + (gui.connected ? "ok" : gui.phase === "error" ? "err" : "warn");
    }
    if (gui.last_error && (gui.phase === "error" || gui.phase === "reconnecting")) {
      showToast(gui.last_error, "err");
    }
    const set = (id, v) => { const n = gEl(id); if (n) n.textContent = String(v); };
    set("guiElapsed", gui.scan_elapsed_s || 0);
    set("guiBandPkts", gui.band_packets || 0);
    set("guiOtherPkts", gui.other_packets || 0);
    set("guiAttempt", gui.attempt || 0);
    if (gui.config) {
      set("guiCfgSummary", gui.config.device_id_configured
        ? gui.config.device_id_masked + (gui.config.auth_key_valid ? " · 密钥就绪" : " · 密钥无效")
        : "未配置设备");
      if (gEl("cfgDeviceId") && gui.config.device_id_masked) {
        gEl("cfgDeviceId").placeholder = "当前: " + gui.config.device_id_masked + " (留空保持不变)";
      }
      if (gEl("cfgDeviceName") && !gEl("cfgDeviceName").value && gui.config.device_name) {
        gEl("cfgDeviceName").value = gui.config.device_name;
      }
      if (gEl("cfgBandTz") && !gEl("cfgBandTz").value && gui.config.band_tz) {
        gEl("cfgBandTz").value = gui.config.band_tz;
      }
    }
    renderSteps(gui);
    renderTips(gui);
    renderPlaybooks(gui);
    if (gui.last_playbook) renderPlaybookOutput(gui.last_playbook);
    else if (gui.last_doctor) renderPlaybookOutput(gui.last_doctor);

    const logBox = gEl("guiLogs");
    if (logBox && !logBox.dataset.hydrated && Array.isArray(gui.logs)) {
      logBox.dataset.hydrated = "1";
      logBox.textContent = "";
      gui.logs.forEach(appendLogLine);
    }
    if (!userToggledCenter && gEl("guiCenter")) {
      gEl("guiCenter").classList.toggle("hidden", gui.phase === "streaming");
    }
  }

  async function runPlaybook(id, btn) {
    if (btn) btn.disabled = true;
    showToast("正在执行剧本: " + id + "…", "warn");
    try {
      const res = await apiJson("/api/gui/playbook", "POST", { id: id });
      renderPlaybookOutput(res);
      showToast(res.summary || "执行完成", res.ok ? "ok" : "err");
      applyGuiState(await apiJson("/api/gui/state", "GET"));
    } catch (err) {
      showToast(err.message, "err");
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function bindControls() {
    const on = (id, fn) => { const n = gEl(id); if (n) n.onclick = fn; };
    on("guiConnectBtn", async () => {
      try {
        const histVal = Number((gEl("optHistoryDays") || {}).value || 0);
        const state = await apiJson("/api/gui/connect", "POST", {
          demo: Boolean((gEl("optDemo") || {}).checked),
          imu: Boolean((gEl("optImu") || {}).checked),
          workout: Boolean((gEl("optWorkout") || {}).checked),
          sync_history_days: histVal > 0 ? histVal : null,
        });
        userToggledCenter = false;
        applyGuiState(state);
      } catch (err) { showToast(err.message, "err"); }
    });
    on("guiStopBtn", async () => {
      try { applyGuiState(await apiJson("/api/gui/disconnect", "POST", {})); }
      catch (err) { showToast(err.message, "err"); }
    });
    on("guiDoctorBtn", async () => {
      showToast("正在运行环境自检…", "warn");
      try {
        const res = await apiJson("/api/gui/doctor", "GET");
        renderPlaybookOutput(res);
        showToast(res.summary, res.ok ? "ok" : "warn");
        applyGuiState(await apiJson("/api/gui/state", "GET"));
      } catch (err) { showToast(err.message, "err"); }
    });
    on("guiToggleCenterBtn", () => {
      const center = gEl("guiCenter");
      if (!center) return;
      userToggledCenter = true;
      center.classList.toggle("hidden");
    });
    on("guiConfigBtn", () => { if (gEl("guiConfigDrawer")) gEl("guiConfigDrawer").classList.toggle("hidden"); });
    on("guiScanBtn", async () => {
      const wrap = gEl("guiScanResults");
      if (wrap) wrap.textContent = "正在扫描 12 秒（手环广播较慢，请耐心等待）…";
      try {
        const res = await apiJson("/api/gui/scan", "POST", { duration: 12 });
        if (!wrap) return;
        wrap.textContent = "";
        (res.devices || []).forEach((d) => {
          const b = mk("button", "gui-btn sm" + (d.is_band ? " primary" : ""),
            (d.name || "Unknown") + " (" + d.address + ", " + d.rssi + "dBm)");
          b.onclick = () => { if (gEl("cfgDeviceId")) gEl("cfgDeviceId").value = d.address; };
          wrap.appendChild(b);
        });
        if (!(res.devices || []).length) wrap.textContent = "未扫描到设备，请确认手机蓝牙已关闭。";
      } catch (err) { if (wrap) wrap.textContent = err.message; }
    });
    on("guiSaveCfgBtn", async () => {
      try {
        await apiJson("/api/gui/config", "POST", {
          device_id: (gEl("cfgDeviceId") || {}).value || "",
          auth_key: (gEl("cfgAuthKey") || {}).value || "",
          device_name: (gEl("cfgDeviceName") || {}).value || "",
          band_tz: (gEl("cfgBandTz") || {}).value || "",
        });
        if (gEl("cfgAuthKey")) gEl("cfgAuthKey").value = "";
        showToast("配置已安全保存至 .env (0600)", "ok");
        applyGuiState(await apiJson("/api/gui/state", "GET"));
      } catch (err) { showToast(err.message, "err"); }
    });
    on("guiExportBtn", async () => {
      try {
        const res = await apiJson("/api/gui/export-csv", "POST", {});
        const total = Object.values(res.tables || {}).reduce((s, t) => s + (t.rows || 0), 0);
        showToast("已导出 CSV (" + total + " 行) -> " + res.csv_dir, "ok");
      } catch (err) { showToast(err.message, "err"); }
    });
    on("guiCopyCmdBtn", async () => {
      const txt = (gEl("guiCmdText") || {}).textContent || "";
      if (txt && navigator.clipboard) {
        await navigator.clipboard.writeText(txt);
        showToast("终端修复命令已复制到剪贴板", "ok");
      }
    });
  }

  bindControls();
  apiJson("/api/gui/state", "GET").then(applyGuiState).catch(() => {});
  window.MiBandGui = { applyGuiState, appendLogLine, renderPlaybookOutput };
})();
