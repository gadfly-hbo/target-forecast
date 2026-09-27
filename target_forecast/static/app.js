/* 目标测算工作台 · 前端逻辑（无框架、无外部依赖） */
"use strict";

const S = {
  view: "all",            // 'all' | 平台名
  scenario: "基准",
  stateInfo: null,        // /api/state 结果
  defaults: null,         // config.yaml 的默认三档参数
  params: null,           // 当前参数（可编辑）
  calc: null,             // /api/calc 结果
};

const $ = (sel) => document.querySelector(sel);
const SCENARIOS = ["保守", "基准", "挑战"];

const PARAM_GROUPS = [
  { key: "person", title: "人 · 新老客", note: "驱动人视角：新客数×新客客单 + 老客数×复购频次×老客客单",
    fields: [["new_customers_growth", "新客数"], ["new_arpu_growth", "新客客单"], ["old_customers_growth", "老客月活"], ["old_freq_growth", "复购频次"], ["old_aov_growth", "老客客单"]] },
  { key: "field", title: "场 · UV×转化×客单", note: "仅对填报UV的平台生效（模式B）",
    fields: [["uv_growth", "UV"], ["cvr_growth", "转化率"], ["aov_growth", "整体客单"]] },
];

/* ---------- 格式化 ---------- */
const fmtInt = (v) => (v == null ? "—" : Math.round(v).toLocaleString("zh-CN"));
const fmtWan = (v) => {
  if (v == null) return "—";
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + " 亿";
  if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(1) + " 万";
  return Math.round(v).toLocaleString("zh-CN");
};
const fmtPct = (v, d = 1) => (v == null ? "—" : (v * 100).toFixed(d) + "%");
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ---------- 启动 ---------- */
async function boot() {
  S.stateInfo = await (await fetch("api/state")).json();
  if (S.stateInfo.error) { document.body.textContent = "加载失败：" + S.stateInfo.error; return; }
  S.defaults = S.stateInfo.scenarios;
  S.params = JSON.parse(JSON.stringify(S.defaults));
  // 助手调参（P3）：服务端持久化的情景补丁在启动时应用，刷新后生效
  try {
    const ap = await (await fetch("api/assistant_params")).json();
    for (const [sc, patch] of Object.entries(ap.scenarios || {})) {
      S.params[sc] = { ...(S.params[sc] || {}), ...patch };
    }
  } catch { /* 无补丁或不可达时保持默认 */ }
  buildNav();
  buildSeg();
  buildParamsPane();
  buildCaliberPane();
  buildExportsPane();
  bindEvents();
  await recalc();
}

async function recalc() {
  const r = await fetch("api/calc", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenarios: S.params }),
  });
  const data = await r.json();
  if (data.error) { toast("测算失败：" + data.error); return; }
  S.calc = data;
  render();
  $("#sb-time").textContent = "最近测算 " + new Date().toLocaleTimeString("zh-CN");
}

/* ---------- 侧栏 / 情景 ---------- */
function platformList() { return Object.keys(S.calc ? S.calc.platforms : {}); }

function buildNav() {
  const names = Object.keys(S.stateInfo.platforms);
  const mode = (p) => S.stateInfo.platforms[p].mode;
  const rows = [
    { id: "all", label: "全渠道", meta: names.length + " 平台 · 汇总" },
    ...names.map((p) => ({ id: p, label: p, meta: "模式" + mode(p) })),
  ];
  $("#nav").innerHTML =
    '<div class="nav-group-label">视图</div>' +
    rows.map((r) =>
      `<button type="button" class="nav-item${S.view === r.id ? " active" : ""}" data-view="${esc(r.id)}">
        <span>${esc(r.label)}</span><span class="nav-meta">${esc(r.meta)}</span></button>`).join("");
}

function buildSeg() {
  $("#scenario-seg").querySelectorAll("button").forEach((b) => {
    b.classList.toggle("active", b.dataset.s === S.scenario);
  });
}

/* ---------- Inspector：参数面板 ---------- */
function tierGrowthFields() {
  const t = S.params[S.scenario].tier_growth;
  return [["爆款", t["爆款"]], ["腰部", t["腰部"]], ["尾部", t["尾部"]], ["新品", t["新品"]]];
}

function buildParamsPane() {
  const p = S.params[S.scenario];
  const group = (g) => `
    <div class="param-group">
      <div class="param-group-h"><span class="param-group-title">${g.title}</span></div>
      <div class="fld-row">
        ${g.fields.map(([k, label]) => `
          <div class="fld">
            <label>${label}增速 %</label>
            <input type="number" step="0.5" min="-50" max="200" data-param="${k}" value="${(p[k] * 100).toFixed(1)}">
          </div>`).join("")}
      </div>
      ${g.note ? `<div class="param-note">${g.note}</div>` : ""}
    </div>`;
  const tierGroup = `
    <div class="param-group">
      <div class="param-group-h"><span class="param-group-title">货 · 款梯队</span></div>
      <div class="fld-row">
        ${tierGrowthFields().map(([t, v]) => `
          <div class="fld">
            <label>${t}增速 %</label>
            <input type="number" step="0.5" min="-50" max="200" data-tier="${t}" value="${(v * 100).toFixed(1)}">
          </div>`).join("")}
      </div>
      <div class="param-note">仅模式A（订单明细）平台生效；爆款守、腰部攻、尾部清、新品打爆。</div>
    </div>`;
  $("#params-pane").innerHTML = `
    <div class="param-note" style="margin:0 2px 10px">当前编辑：<b>${S.scenario}</b> 情景（在顶部切换）。改动后自动重算。</div>
    ${PARAM_GROUPS.map(group).join("")}${tierGroup}
    <div class="insp-actions">
      <button type="button" class="btn sm" id="reset-params">恢复默认参数</button>
    </div>`;
  $("#reset-params").addEventListener("click", () => {
    S.params = JSON.parse(JSON.stringify(S.defaults));
    buildParamsPane();
    recalc();
    toast("已恢复 config.yaml 默认参数");
  });
  $("#params-pane").querySelectorAll("input[data-param]").forEach((inp) => {
    inp.addEventListener("input", () => onParamInput(inp));
  });
  $("#params-pane").querySelectorAll("input[data-tier]").forEach((inp) => {
    inp.addEventListener("input", () => onTierInput(inp));
  });
}

let debounceTimer = null;
function onParamInput(inp) {
  S.params[S.scenario][inp.dataset.param] = parseFloat(inp.value || "0") / 100;
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(recalc, 400);
}
function onTierInput(inp) {
  S.params[S.scenario].tier_growth[inp.dataset.tier] = parseFloat(inp.value || "0") / 100;
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(recalc, 400);
}

function buildExportsPane() {
  const plats = Object.keys(S.stateInfo.platforms);
  $("#exports-pane").innerHTML = `
    <p class="meta">下载最近一次 <code>main.py run</code> 生成的产物；文件不存在时会提示先运行生成。</p>
    <p><a href="api/export/report" download>📊 目标测算报告.xlsx</a></p>
    <p class="meta">中间月度指标（CSV）：</p>
    <ul class="caliber-list">
      ${plats.map((p) => `<li><a href="api/export/metrics/${encodeURIComponent(p)}" download>${esc(p)} · 月度指标.csv</a></li>`).join("")}
    </ul>`;
}

function buildCaliberPane() {
  const c = S.stateInfo.caliber;
  $("#caliber-pane").innerHTML = `
    <ul class="caliber-list">
      <li><b>GMV</b>：实付净额（已扣退款）。</li>
      <li><b>新客</b>：前 ${c.new_customer_window_days} 天无购买（滚动口径），当月身份由当月首单决定；明细左截断使历史首月新客偏高。</li>
      <li><b>梯队</b>：单款GMV降序累计 ≤${Math.round(c.tier_pareto_pct * 100)}% 爆款、末段 ≤${Math.round(c.tier_tail_pct * 100)}% 尾部、其余腰部；${c.new_product_days} 天内新上架记新品。</li>
      <li><b>复购频次</b>：老客订单 ÷ 老客人数（月内）。</li>
      <li><b>基线</b>：最近 ${c.baseline_months} 个月；流量型按季节分摊，价值型平推。</li>
      <li><b>主口径</b>：模式A=人视角（订单无UV）；模式B且有UV=场视角。</li>
      <li><b>全渠道</b>：平台加总、跨平台不去重；客单/转化率按分子分母重算。</li>
      <li><b>测算期</b>：历史末月后 ${S.stateInfo.target_months} 个月。</li>
    </ul>`;
}

/* ---------- 渲染 ---------- */
function render() {
  buildNav();
  $("#view-title").textContent = (S.view === "all" ? "全渠道" : S.view) + " · " + S.scenario;
  $("#range-meta").textContent = S.calc.target_range.length
    ? `测算期 ${S.calc.target_range[0]} ~ ${S.calc.target_range[S.calc.target_range.length - 1]}` : "";
  const sbMode = $("#sb-mode");
  sbMode.textContent = S.stateInfo.demo_used ? "演示数据 DEMO" : "正式数据";
  sbMode.className = "chip " + (S.stateInfo.demo_used ? "warn" : "ok");
  const nOrders = Object.entries(S.stateInfo.platforms).filter(([, v]) => v.mode === "A").length;
  $("#sb-src").textContent = `workspace/forecast/ · ${Object.keys(S.stateInfo.platforms).length} 平台（明细${nOrders} · 聚合${Object.keys(S.stateInfo.platforms).length - nOrders}）`;
  renderBanner();
  renderKpis();
  renderChart();
  renderViews();
  renderAnnual();
  renderGoods();
  renderDetail();
}

function scopedCheckRows() {
  return S.calc.check.filter((r) => r.scenario === S.scenario && (S.view === "all" || r.platform === S.view));
}

function renderBanner() {
  const rows = scopedCheckRows();
  let worst = 0, worstView = "";
  for (const r of rows) {
    for (const v of ["人", "场", "货"]) {
      const d = r[v + "视角GMV差异"];
      if (d != null && Math.abs(d) > Math.abs(worst)) { worst = d; worstView = v; }
    }
  }
  if (rows.length === 0) { $("#check-banner").innerHTML = ""; return; }
  if (Math.abs(worst) > 0.05) {
    $("#check-banner").innerHTML = `
      <div class="banner warn"><span class="b-title">⚠ 交叉校验未通过</span>
      <span class="b-detail">${esc(worstView)}视角与主口径最大差 ${fmtPct(Math.abs(worst))}（>5%）——该组参数假设与其他视角矛盾，建议复核右栏参数。</span></div>`;
  } else {
    $("#check-banner").innerHTML = `
      <div class="banner ok"><span class="b-title">✓ 交叉校验通过</span>
      <span class="b-detail">各视角与主口径差异均 ≤5%。</span></div>`;
  }
}

function annualSums() {
  if (S.view === "all") {
    const rows = S.calc.consolidated.filter((r) => r.scenario === S.scenario);
    const sum = (k) => rows.reduce((a, r) => a + (r[k] || 0), 0);
    return { gmv: sum("GMV_主口径"), newGmv: sum("新客GMV"), oldGmv: sum("老客GMV"),
             orders: sum("订单数"), uv: rows.reduce((a, r) => a + (r["UV"] || 0), 0),
             cvr: rows.length ? rows[rows.length - 1]["全渠道转化率"] : null };
  }
  const r = S.calc.platforms[S.view];
  const rows = r.person.filter((x) => x.scenario === S.scenario);
  const sum = (k) => rows.reduce((a, x) => a + (x[k] || 0), 0);
  const base = r.baseline;
  return { gmv: sum("gmv"), newGmv: sum("new_gmv"), oldGmv: sum("old_gmv"),
           orders: sum("orders"), baseGmv: base.annual_gmv, uv: null, cvr: null,
           aov: sum("gmv") / Math.max(sum("orders"), 1e-9) };
}

function renderKpis() {
  const a = annualSums();
  let baseGmv = a.baseGmv;
  if (S.view === "all") {
    baseGmv = Object.values(S.calc.platforms).reduce((s, p) => s + p.baseline.annual_gmv, 0);
  }
  const growth = baseGmv ? a.gmv / baseGmv - 1 : null;
  const cards = [
    { label: "目标年度 GMV（主口径）", value: fmtWan(a.gmv), sub: `基期 ${fmtWan(baseGmv)}`, cls: growth != null && growth >= 0 ? "up" : "down" },
    { label: "增速", value: fmtPct(growth), sub: S.scenario + " 情景", cls: growth != null && growth >= 0 ? "up" : "down" },
    { label: "新客 GMV 占比", value: fmtPct(a.gmv ? a.newGmv / a.gmv : null), sub: `新客 ${fmtWan(a.newGmv)} · 老客 ${fmtWan(a.oldGmv)}` },
  ];
  if (S.view === "all") {
    const last = S.calc.consolidated.filter((r) => r.scenario === S.scenario);
    const aov = last.length ? last[last.length - 1]["全渠道客单"] : null;
    const cvr = last.length ? last[last.length - 1]["全渠道转化率"] : null;
    cards.push({ label: "全渠道客单", value: aov != null ? "¥" + aov.toFixed(1) : "—", sub: "ΣGMV ÷ Σ订单数" });
    cards.push({ label: "全渠道转化率", value: fmtPct(cvr), sub: last.length ? last[last.length - 1]["转化率覆盖口径"] : "" });
  } else {
    cards.push({ label: "客单（年化）", value: a.aov != null ? "¥" + a.aov.toFixed(1) : "—", sub: "人视角 GMV ÷ 订单" });
    cards.push({ label: "主口径", value: S.calc.platforms[S.view].main_view + "视角", sub: "模式" + S.calc.platforms[S.view].mode + (S.calc.platforms[S.view].main_view === "场" ? " · 有UV" : " · 订单无UV") });
  }
  $("#kpis").innerHTML = cards.map((c) => `
    <div class="kpi"><div class="kpi-label">${c.label}</div>
    <div class="kpi-value ${c.cls || ""}">${c.value}</div>
    <div class="kpi-sub">${c.sub}</div></div>`).join("");
}

/* ---------- SVG 堆叠柱状图 ---------- */
function chartRows() {
  if (S.view === "all") {
    return S.calc.consolidated.filter((r) => r.scenario === S.scenario)
      .map((r) => ({ month: r.month, neu: r["新客GMV"], old: r["老客GMV"] }));
  }
  return S.calc.platforms[S.view].person.filter((r) => r.scenario === S.scenario)
    .map((r) => ({ month: r.month, neu: r.new_gmv, old: r.old_gmv }));
}

function renderChart() {
  const rows = chartRows();
  if (!rows.length) { $("#chart").innerHTML = '<div class="param-note">无数据</div>'; return; }
  const W = 812, H = 260, padL = 56, padB = 26, padT = 12, padR = 8;
  const iw = W - padL - padR, ih = H - padT - padB;
  const n = rows.length;
  const maxTotal = Math.max(...rows.map((r) => r.neu + r.old), 1);
  const nice = niceCeil(maxTotal);
  const bw = Math.min(38, (iw / n) * 0.62);
  const y = (v) => padT + ih * (1 - v / nice);
  const monthLabel = (m) => m.slice(5).replace(/^0/, "") + "月";

  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="月度目标GMV堆叠图">`;
  for (let i = 0; i <= 4; i++) {
    const v = (nice / 4) * i;
    svg += `<line x1="${padL}" y1="${y(v)}" x2="${W - padR}" y2="${y(v)}" stroke="#e2e0db" stroke-width="1"/>
            <text x="${padL - 6}" y="${y(v) + 3.5}" text-anchor="end" font-size="10" fill="#8a877e">${fmtWan(v)}</text>`;
  }
  rows.forEach((r, i) => {
    const cx = padL + (iw / n) * (i + 0.5);
    const x = cx - bw / 2;
    const total = r.neu + r.old;
    svg += `<rect x="${x}" y="${y(r.old)}" width="${bw}" height="${Math.max(y(0) - y(r.old), 0)}" rx="2"
              fill="#e6f4f2" stroke="#bfe3de"><title>${r.month} 老客GMV ${fmtInt(r.old)}</title></rect>`;
    svg += `<rect x="${x}" y="${y(total)}" width="${bw}" height="${Math.max(y(r.old) - y(total), 0)}" rx="2"
              fill="#0f766e"><title>${r.month} 新客GMV ${fmtInt(r.neu)}</title></rect>`;
    svg += `<text x="${cx}" y="${H - 8}" text-anchor="middle" font-size="10" fill="#5b5952">${monthLabel(r.month)}</text>`;
  });
  svg += "</svg>";
  $("#chart").innerHTML = svg;
}

function niceCeil(v) {
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  const steps = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
  for (const s of steps) { if (s * mag >= v) return s * mag; }
  return 10 * mag;
}

/* ---------- 三视角 / 平台年度 / 商品结构 ---------- */
function renderViews() {
  const rows = scopedCheckRows();
  const views = [
    { name: "人", key: "人视角GMV" },
    { name: "场", key: "场视角GMV" },
    { name: "货", key: "货视角GMV" },
  ];
  let html = '<table class="tbl"><tr><th>视角</th><th>年化GMV</th><th>覆盖</th><th>vs 覆盖内主口径</th><th>状态</th></tr>';
  for (const v of views) {
    // 每个视角只与其「覆盖范围内」的平台主口径对比（场仅填报UV平台、货仅明细平台）
    let viewSum = 0, mainSum = 0;
    const covered = new Set(), all = new Set();
    for (const r of rows) {
      all.add(r.platform);
      if (r[v.key] == null) continue;
      viewSum += r[v.key]; mainSum += r["主口径GMV"]; covered.add(r.platform);
    }
    const has = covered.size > 0;
    const diff = has && mainSum ? viewSum / mainSum - 1 : null;
    const coverage = S.view === "all" ? `${covered.size}/${all.size} 平台` : (has ? "本平台" : "—");
    const chip = !has ? '<span class="chip ghost">无数据</span>'
      : Math.abs(diff) <= 0.05 ? '<span class="chip ok">✓ ≤5%</span>'
      : '<span class="chip warn">⚠ 超5%</span>';
    html += `<tr><td>${v.name}视角</td><td>${has ? fmtWan(viewSum) : "—"}</td>
      <td class="muted">${coverage}</td>
      <td class="${diff == null ? "muted" : diff >= 0 ? "pos" : "neg"}">${fmtPct(diff)}</td><td>${chip}</td></tr>`;
  }
  html += `</table><div class="param-note">主口径 = ${S.view === "all" ? "各平台主口径加总" : S.calc.platforms[S.view].main_view + "视角"}；对比只在视角覆盖的平台范围内进行。</div>`;
  $("#views-card").innerHTML = html;
}

function renderAnnual() {
  const rows = S.calc.platform_annual.filter((r) => r.scenario === S.scenario);
  let html = '<table class="tbl"><tr><th>平台</th><th>基期GMV</th><th>目标GMV</th><th>增速</th></tr>';
  for (const r of rows) {
    const mode = S.calc.platforms[r.platform].mode;
    html += `<tr><td>${esc(r.platform)} <span class="chip ghost">模式${mode}</span></td>
      <td class="muted">${fmtWan(r["基期年化GMV"])}</td><td>${fmtWan(r["目标年度GMV"])}</td>
      <td class="${r["增速"] >= 0 ? "pos" : "neg"}">${fmtPct(r["增速"])}</td></tr>`;
  }
  $("#annual-card").innerHTML = html + "</table>";
}

function renderGoods() {
  const src = S.calc.goods.filter((r) => S.view === "all" || r.platform === S.view);
  if (!src.length) {
    $("#goods-card").style.display = "none";
    return;
  }
  $("#goods-card").style.display = "";
  const agg = new Map();
  for (const r of src) {
    const k = r["品类"] + "|" + r["梯队"];
    const cur = agg.get(k) || { cat: r["品类"], tier: r["梯队"], n: 0, v: 0 };
    cur.n += r["款数"]; cur.v += r[S.scenario] || 0;
    agg.set(k, cur);
  }
  const order = { "爆款": 0, "腰部": 1, "新品": 2, "尾部": 3 };
  const rows = [...agg.values()].sort((a, b) => a.cat.localeCompare(b.cat, "zh") || order[a.tier] - order[b.tier]);
  const total = rows.reduce((s, r) => s + r.v, 0);
  let html = '<table class="tbl"><tr><th>品类</th><th>梯队</th><th>款数</th><th>目标GMV</th><th>占比</th></tr>';
  for (const r of rows) {
    const chipCls = { "爆款": "accent", "腰部": "ghost", "新品": "ok", "尾部": "warn" }[r.tier];
    html += `<tr><td>${esc(r.cat)}</td><td><span class="chip ${chipCls}">${r.tier}</span></td>
      <td>${r.n}</td><td>${fmtWan(r.v)}</td><td>${fmtPct(total ? r.v / total : null)}</td></tr>`;
  }
  $("#goods").innerHTML = html + "</table>";
}

function renderDetail() {
  let html;
  if (S.view === "all") {
    const rows = S.calc.consolidated.filter((r) => r.scenario === S.scenario);
    html = '<tr><th>月份</th><th>GMV(主口径)</th><th>新客GMV</th><th>老客GMV</th><th>订单数</th><th>UV</th><th>客单</th><th>转化率</th></tr>' +
      rows.map((r) => `<tr><td>${r.month}</td><td>${fmtInt(r["GMV_主口径"])}</td><td>${fmtInt(r["新客GMV"])}</td>
        <td>${fmtInt(r["老客GMV"])}</td><td>${fmtInt(r["订单数"])}</td><td>${fmtInt(r["UV"])}</td>
        <td>${r["全渠道客单"] != null ? "¥" + r["全渠道客单"].toFixed(1) : "—"}</td>
        <td>${fmtPct(r["全渠道转化率"])}</td></tr>`).join("");
  } else {
    const rows = S.calc.platforms[S.view].person.filter((r) => r.scenario === S.scenario);
    html = '<tr><th>月份</th><th>新客数</th><th>新客客单</th><th>老客数</th><th>频次</th><th>老客客单</th><th>新客GMV</th><th>老客GMV</th><th>GMV</th><th>订单</th></tr>' +
      rows.map((r) => `<tr><td>${r.month}</td><td>${fmtInt(r.new_customers)}</td><td>¥${r.new_arpu.toFixed(0)}</td>
        <td>${fmtInt(r.old_customers)}</td><td>${r.old_freq.toFixed(2)}</td><td>¥${r.old_aov.toFixed(0)}</td>
        <td>${fmtInt(r.new_gmv)}</td><td>${fmtInt(r.old_gmv)}</td><td>${fmtInt(r.gmv)}</td><td>${fmtInt(r.orders)}</td></tr>`).join("");
  }
  $("#detail").innerHTML = html;
}

/* ---------- 事件 ---------- */
function bindEvents() {
  $("#nav").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-view]");
    if (!btn) return;
    S.view = btn.dataset.view;
    buildNav();
    render();
  });
  $("#scenario-seg").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-s]");
    if (!btn) return;
    S.scenario = btn.dataset.s;
    buildSeg();
    buildParamsPane();
    render();
  });
  document.querySelector(".insp-tabs").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-pane]");
    if (!btn) return;
    document.querySelectorAll(".insp-tabs button").forEach((b) => b.classList.toggle("active", b === btn));
    $("#params-pane").hidden = btn.dataset.pane !== "params-pane";
    $("#caliber-pane").hidden = btn.dataset.pane !== "caliber-pane";
    $("#exports-pane").hidden = btn.dataset.pane !== "exports-pane";
  });
  $("#reload").addEventListener("click", async () => {
    S.stateInfo = await (await fetch("api/state?reload=1")).json();
    if (S.stateInfo.error) { toast("重载失败：" + S.stateInfo.error); return; }
    S.defaults = S.stateInfo.scenarios;
    S.params = JSON.parse(JSON.stringify(S.defaults));
    buildParamsPane();
    buildCaliberPane();
    await recalc();
    toast("已重新载入 workspace/forecast/ 数据");
  });
}

function toast(msg) {
  let t = document.querySelector(".toast");
  if (!t) {
    t = document.createElement("div");
    t.className = "toast";
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove("show"), 2600);
}

boot();
