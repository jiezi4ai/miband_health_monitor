// Co-axis view: activity bars + heart-rate line + sleep/not-worn band on one
// shared time axis.  A missing bucket stays empty in every channel: no zero
// bar, no invented line segment, no sleep colour.
function renderCoAxis() {
  const canvas = document.getElementById("coChart");
  const scale = document.getElementById("coScale");
  if (!canvas || !scale) return;
  const points = (DATA.combined && DATA.combined.points) || [];
  const bucket = (DATA.combined && DATA.combined.bucket_seconds) || 3600;
  const bands = DATA.activity.bands || {REST: 0, ACTIVE: 1, SLEEP: 2, NONWEAR: 3};

  const draw = () => {
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth || 600, height = canvas.clientHeight || 190;
    canvas.width = width * dpr; canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    if (!points.length) {
      ctx.fillStyle = "#8b98a5"; ctx.font = "12px sans-serif";
      ctx.fillText("暂无数据", 12, height / 2);
      scale.textContent = "";
      return;
    }

    const pad = {left: 40, right: 42, top: 10, bottom: 34};
    const bandH = 14;
    const plotW = width - pad.left - pad.right;
    const plotBottom = height - pad.bottom - bandH - 6;
    const plotH = plotBottom - pad.top;
    const x0 = points[0][0], x1 = points[points.length - 1][0];
    const spanX = (x1 - x0) || 1;
    const sx = ts => pad.left + ((ts - x0) / spanX) * plotW;

    const steps = points.map(p => p[1]).filter(v => typeof v === "number");
    const maxSteps = Math.max(1, ...steps);
    const niceMax = Math.ceil(maxSteps / 10) * 10 || 10;
    const hrs = points.map(p => p[2]).filter(v => typeof v === "number");
    const hrLo = Math.min(40, hrs.length ? Math.floor(Math.min(...hrs) - 4) : 40);
    const hrHi = Math.max(180, hrs.length ? Math.ceil(Math.max(...hrs) + 4) : 180);
    const sy = v => plotBottom - (v / niceMax) * plotH;
    const hy = v => plotBottom - ((v - hrLo) / ((hrHi - hrLo) || 1)) * plotH;

    ctx.font = "11px -apple-system, 'PingFang SC', sans-serif";
    ctx.strokeStyle = "#2a323c"; ctx.lineWidth = 1;
    for (let i = 0; i <= 3; i++) {
      const y = pad.top + plotH * i / 3;
      ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(width - pad.right, y); ctx.stroke();
      ctx.fillStyle = "#8b98a5";
      ctx.fillText(Math.round(niceMax * (1 - i / 3)).toLocaleString(), 4, y + 4);
      ctx.fillText(Math.round(hrHi - (hrHi - hrLo) * i / 3), width - pad.right + 6, y + 4);
    }

    // Sleep / not-worn strip: the band codes come from the payload (B-9).
    const hatch = (() => {
      const tile = document.createElement("canvas");
      tile.width = 6; tile.height = 6;
      const t = tile.getContext("2d");
      t.fillStyle = "#1e2630"; t.fillRect(0, 0, 6, 6);
      t.strokeStyle = "#4a5866"; t.lineWidth = 1;
      t.beginPath(); t.moveTo(-1, 7); t.lineTo(7, -1); t.stroke();
      return ctx.createPattern(tile, "repeat");
    })();
    const stripColors = {
      [bands.REST]: "#33404f", [bands.ACTIVE]: "#4ade80",
      [bands.SLEEP]: "#8b5cf6"
    };
    const cellW = Math.max(1, plotW / Math.max(1, points.length - 1) * 0.9);
    points.forEach((p, index) => {
      const code = p[3];
      if (code === null || code === undefined) return;  // no record: leave unset
      ctx.fillStyle = code === bands.NONWEAR ? hatch : (stripColors[code] || "#33404f");
      const x = sx(p[0]) - cellW / 2;
      ctx.fillRect(Math.max(pad.left, x), plotBottom + 6, cellW, bandH);
    });

    // Activity bars: only for buckets that actually have band-side minutes.
    points.forEach(p => {
      if (typeof p[1] !== "number") return;
      const x = sx(p[0]);
      const h = Math.max(0, plotBottom - sy(p[1]));
      ctx.fillStyle = "rgba(74,222,128,.65)";
      ctx.fillRect(x - Math.max(1, cellW / 2), sy(p[1]), Math.max(1, cellW), h);
    });

    // Heart rate line: break at a missing value or a runs of absent buckets.
    ctx.strokeStyle = "#ff5c7a"; ctx.lineWidth = 1.6;
    const hrPath = new Path2D();
    let pen = false, lastTs = null;
    points.forEach(p => {
      const bpm = p[2];
      if (typeof bpm !== "number" || (lastTs !== null && p[0] - lastTs > bucket * 1.5)) {
        pen = false;
      } else {
        const x = sx(p[0]), y = hy(bpm);
        if (!pen) { hrPath.moveTo(x, y); pen = true; } else { hrPath.lineTo(x, y); }
      }
      lastTs = p[0];
    });
    ctx.stroke(hrPath);

    ctx.fillStyle = "#8b98a5";
    const fmt = bucket >= 86400
      ? {month: "2-digit", day: "2-digit"}
      : {month: "2-digit", day: "2-digit", hour: "2-digit"};
    [points[0], points[Math.floor(points.length / 2)], points[points.length - 1]]
      .filter(Boolean).forEach(p => {
        const label = new Date(p[0] * 1000).toLocaleString("zh-CN", fmt);
        ctx.fillText(label, Math.min(width - pad.right - 88, Math.max(pad.left, sx(p[0]) - 24)), height - 5);
      });
    scale.textContent =
      `绿柱=步数（左轴） · 粉线=心率（右轴） · 底部色带=睡眠/未佩戴 · 每格 ${
        bucket >= 86400 ? "1 天" : bucket >= 3600 ? "1 小时" : "10 分钟"
      } · 缺口留空不补零`;
  };
  requestAnimationFrame(draw);
  window.addEventListener("resize", () => requestAnimationFrame(draw));
}
