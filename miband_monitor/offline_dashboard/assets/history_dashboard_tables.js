function renderSpo2() {
  const host = document.getElementById("spo2Panel");
  if (!DATA.spo2.length) {
    host.appendChild(el("div", "empty", "该窗口内没有点测血氧记录。"));
    return;
  }
  const table = el("table");
  const head = el("tr");
  ["时间", "血氧", "类型"].forEach(name => head.appendChild(el("th", "", name)));
  table.appendChild(head);
  DATA.spo2.slice().reverse().forEach(item => {
    const row = el("tr");
    row.appendChild(el("td", "", item.time));
    row.appendChild(el("td", "num", `${item.spo2}%`));
    row.appendChild(el("td", "", item.auto ? "自动测量" : "手动测量"));
    table.appendChild(row);
  });
  host.appendChild(table);
}

function renderSports() {
  const host = document.getElementById("sportsPanel");
  if (!host) return;
  const sports = DATA.sports || [];
  if (!sports.length) {
    host.appendChild(el("div", "empty",
      "该窗口内没有手环侧运动总结（需连接手环并加 --sync-history --sync-sports）。"));
    return;
  }
  const table = el("table");
  const head = el("tr");
  ["开始", "结束", "类型", "时长", "步数", "距离", "消耗", "心率(均/峰)"]
    .forEach(name => head.appendChild(el("th", "", name)));
  table.appendChild(head);
  sports.slice().reverse().forEach(item => {
    const row = el("tr");
    row.appendChild(el("td", "", item.start));
    row.appendChild(el("td", "", item.end));
    row.appendChild(el("td", "", item.kind_name || "--"));
    row.appendChild(el("td", "num", `${Math.round(item.duration_s / 60)} 分`));
    row.appendChild(el("td", "num", Number(item.steps).toLocaleString()));
    row.appendChild(el("td", "num", `${(item.distance_m / 1000).toFixed(2)} km`));
    row.appendChild(el("td", "num", `${Math.round(item.calories)} kcal`));
    row.appendChild(el("td", "num",
      item.average_hr ? `${item.average_hr} / ${item.max_hr}` : "--"));
    table.appendChild(row);
  });
  host.appendChild(table);
}

function renderFooter() {
  const meta = DATA.meta;
  document.getElementById("footer").innerHTML =
    `数据来源：Mi Band 6 BLE 直连同步（活动 ${meta.activity_samples} 分钟 · 心率 ${meta.hr_samples} 条 · 点测血氧 ${meta.spo2_samples} 条 · 整夜血氧 ${meta.spo2_sleep_samples} 条）` +
    ` · 数据库 <code>${meta.source}</code><br>` +
    `睡眠分期为<b>推导值</b>：手环并不直接上报每分钟阶段，这里用 <code>kind</code> 状态机判定睡眠窗口，` +
    `再按心率水平与心率变异性区分深睡与浅睡；腕部无 EEG，结果用于看趋势，不作逐分钟判读。` +
    `深睡/浅睡在无心率时段显示为“无心率”。` +
    `活动条里 <b>斜纹</b> 是手环记录到的“未佩戴”（<code>kind=0xF3</code>，心率无读数），` +
    `<b>空白</b> 是那一分钟手环已经没有数据（通常已被手机 App 取走）——两者含义完全不同，别混看。` +
    `Zepp Life 的六页里，手环佩戴的五夜都没有 REM 一栏，唯一有 REM 的那夜手环未佩戴（另一台设备）；` +
    `手环本身也不产出分期结果（0x48 返回 0 条），因此这里只给深睡/浅睡。`;
}

renderHeader();
renderKpis();
renderSleep();
renderHeartRate();
renderActivity();
renderCoAxis();
renderSteps();
renderSports();
renderSpo2Sleep();
renderSpo2();
renderFooter();