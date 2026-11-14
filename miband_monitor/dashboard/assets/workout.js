"use strict";

(function () {
  const STATE_LABELS = {
    streaming: "实时监测中",
    reconnecting: "断线重连中",
    gap_filling: "历史缺口补齐",
    finished: "运动已结束",
  };

  const ZONE_COLORS = {
    0: "#64748b",
    1: "#38bdf8",
    2: "#4ade80",
    3: "#fbbf24",
    4: "#f97316",
    5: "#ef4444",
  };

  function byId(id) {
    return document.getElementById(id);
  }

  function formatDuration(totalSeconds) {
    const sec = Math.max(0, Math.floor(Number(totalSeconds) || 0));
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    return [h, m, s].map((v) => String(v).padStart(2, "0")).join(":");
  }

  function renderZones(zones) {
    const container = byId("wkZones");
    if (!container || !Array.isArray(zones)) return;
    const totalSec = zones.reduce((acc, z) => acc + (Number(z.seconds) || 0), 0);
    container.textContent = "";
    zones
      .filter((z) => z.zone >= 1)
      .forEach((z) => {
        const sec = Number(z.seconds) || 0;
        const pct = totalSec > 0 ? Math.round((sec / totalSec) * 100) : 0;
        const color = ZONE_COLORS[z.zone] || "#ff5c7a";

        const card = document.createElement("div");
        card.className = "wk-zone";

        const head = document.createElement("div");
        head.className = "wk-zone-head";
        const left = document.createElement("span");
        left.textContent =
          "Z" + String(z.zone) + " " + String(z.label) + " (" +
          String(z.min_bpm) + "-" + String(z.max_bpm) + ")";
        const right = document.createElement("span");
        right.textContent = String(Math.round(sec)) + "s (" + String(pct) + "%)";
        head.appendChild(left);
        head.appendChild(right);

        const bar = document.createElement("div");
        bar.className = "wk-zone-bar";
        const fill = document.createElement("div");
        fill.className = "wk-zone-fill";
        fill.style.width = String(pct) + "%";
        fill.style.background = color;
        bar.appendChild(fill);

        card.appendChild(head);
        card.appendChild(bar);
        container.appendChild(card);
      });
  }

  function mergeGapFillTimeline(hrSeries, timeline, maxPoints) {
    if (!Array.isArray(hrSeries) || !Array.isArray(timeline)) return hrSeries;
    const liveRows = hrSeries.filter((row) => !row._gapFill);
    const byTs = new Map();
    liveRows.forEach((row) => byTs.set(Math.round(row.ts), row));
    timeline.forEach((pt) => {
      if (pt && pt.source === "gap_fill" && typeof pt.bpm === "number") {
        const key = Math.round(pt.ts);
        if (!byTs.has(key)) {
          byTs.set(key, {
            kind: "heart_rate",
            ts: pt.ts,
            iso_time: pt.iso_time,
            bpm: pt.bpm,
            _gapFill: true,
          });
        }
      }
    });
    return Array.from(byTs.values())
      .sort((a, b) => a.ts - b.ts)
      .slice(-(maxPoints || 300));
  }

  function applyWorkout(workout, seriesObj, maxPoints) {
    const panel = byId("workoutPanel");
    if (!panel) return;
    if (!workout) {
      panel.classList.add("hidden");
      return;
    }
    panel.classList.remove("hidden");

    const badge = byId("wkState");
    if (badge) {
      badge.textContent = STATE_LABELS[workout.state] || workout.state || "--";
      badge.className = "wk-badge " + (workout.state || "");
    }
    const set = (id, txt) => { const n = byId(id); if (n) n.textContent = txt; };
    set("wkDuration", formatDuration(workout.elapsed_seconds));
    set("wkReconnects", String(workout.reconnect_count || 0));

    const batWrap = byId("wkBatteryWrap");
    if (workout.battery_pct !== null && workout.battery_pct !== undefined) {
      if (batWrap) batWrap.classList.remove("hidden");
      set("wkBattery", String(workout.battery_pct));
    }

    const gapWrap = byId("wkGapFillWrap");
    const gapCount = Number(workout.gap_filled_count || 0);
    if (gapWrap) {
      gapWrap.classList.toggle("hidden", gapCount <= 0);
      set("wkGapFilled", String(gapCount));
    }

    const steps = workout.steps || {};
    const cal = workout.calories || {};
    const hr = workout.heart_rate || {};
    set("wkSteps", steps.net_steps !== undefined ? String(steps.net_steps) : "--");
    set("wkDist", steps.net_distance_m !== undefined ? String(steps.net_distance_m) : "--");
    set("wkHrKcal", cal.estimated_hr_kcal !== undefined ? Number(cal.estimated_hr_kcal).toFixed(1) : "--");
    set("wkBandKcal", steps.net_band_kcal !== undefined ? String(steps.net_band_kcal) : "--");
    set("wkAvgHr", hr.avg !== null && hr.avg !== undefined ? Number(hr.avg).toFixed(0) : "--");
    set("wkMaxHr", hr.max !== null && hr.max !== undefined ? String(hr.max) : "--");
    set("wkSmoothHr", hr.smoothed !== null && hr.smoothed !== undefined ? Number(hr.smoothed).toFixed(1) : "--");
    set("wkZone", hr.zone ? "Z" + hr.zone.index + " " + hr.zone.label : "--");

    renderZones(workout.zones);

    if (seriesObj && Array.isArray(workout.timeline)) {
      seriesObj.heart_rate = mergeGapFillTimeline(seriesObj.heart_rate, workout.timeline, maxPoints);
    }
  }

  window.MiBandWorkout = {
    applyWorkout: applyWorkout,
    mergeGapFillTimeline: mergeGapFillTimeline,
  };
})();
