/* 投放 ROI 测算前端（无框架、离线）。状态在本页内：plans / scenarios / 当前情景。 */
"use strict";

const S = { state: null, plans: [], scenarios: {}, current: "基准", result: null };

const $ = (id) => document.getElementById(id);
const yuan = (v) => (v == null ? "—" : Number(v).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const pct = (v) => (v == null ? "—" : (v * 100).toFixed(2) + "%");
const num = (v) => (v == null ? "—" : Number(v).toLocaleString("zh-CN", { maximumFractionDigits: 1 }));

async function api(path, body) {
  const opt = body !== undefined
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  const res = await fetch(path.replace(/^\//, ""), opt);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ---------- 启动 ---------- */
async function boot() {
  S.state = await api("api/state");
  S.plans = S.state.plans.map((p) => ({ ...p }));
  // 助手调参（P3）：服务端持久化的计划参数补丁在启动时应用，刷新后生效
  try {
    const ap = await api("api/assistant_params");
    for (const p of S.plans) Object.assign(p, (ap.plans || {})[p.name] || {});
  } catch { /* 无补丁或不可达时保持演示值 */ }
  S.scenarios = JSON.parse(JSON.stringify(S.state.scenarios));
  S.current = Object.keys(S.scenarios).includes("基准") ? "基准" : Object.keys(S.scenarios)[0];
  buildScenarioSeg();
  buildScenarioForms();
  buildPlanForms();
  await recalc();
  $("#sb-version").textContent = `投放 ROI v${S.state.engine_version}`;
}

/* ---------- 测算 ---------- */
let debounceTimer = null;
async function recalc() {
  try {
    S.result = await api("api/calc", { plans: S.plans, scenarios: S.scenarios });
    render();
  } catch (e) {
    $("#result-body").innerHTML = `<tr><td colspan="10" class="neg">测算失败：${esc(e.message)}</td></tr>`;
    $("#result-foot").innerHTML = "";
    $("#stability").textContent = "";
  }
}
const scheduleRecalc = () => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(recalc, 400);
};

/* ---------- 渲染 ---------- */
function buildScenarioSeg() {
  $("#scenarios").innerHTML = Object.keys(S.scenarios)
    .map((s) => `<button type="button" data-s="${esc(s)}" class="${s === S.current ? "active" : ""}">${esc(s)}</button>`)
    .join("");
  $("#scenarios").querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => {
      S.current = b.dataset.s;
      $("#scenarios").querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b));
      render();
    })
  );
}

function buildScenarioForms() {
  $("#scenario-forms").innerHTML = Object.entries(S.scenarios).map(([name, g]) => `
    <div class="scenario-form" data-s="${esc(name)}">
      <b>${esc(name)}</b>
      <label>CVR <input type="number" step="0.01" data-k="cvr_growth" value="${g.cvr_growth}"></label>
      <label>客单 <input type="number" step="0.01" data-k="aov_growth" value="${g.aov_growth}"></label>
    </div>`).join("");
  $("#scenario-forms").querySelectorAll("input").forEach((inp) =>
    inp.addEventListener("input", () => {
      const box = inp.closest(".scenario-form");
      S.scenarios[box.dataset.s][inp.dataset.k] = parseFloat(inp.value) || 0;
      scheduleRecalc();
    })
  );
}

const PARAM_FIELDS = [
  ["spend_cny", "消耗(元)"], ["cpc_cny", "CPC(元)"], ["cvr", "转化率"],
  ["aov_cny", "客单(元)"], ["gross_margin", "毛利率"], ["refund_rate", "退款率"],
];

function buildPlanForms() {
  $("#plan-forms").innerHTML = S.plans.map((p, i) => `
    <div class="plan-form" data-i="${i}">
      <div class="pf-head">
        <input type="text" data-k="name" value="${esc(p.name)}" aria-label="计划名">
        <button type="button" class="btn ghost sm danger" data-del>删除</button>
      </div>
      <div class="pf-grid">
        ${PARAM_FIELDS.map(([k, label]) => `
          <label>${label}<input type="number" step="any" data-k="${k}" value="${p[k]}"></label>`).join("")}
      </div>
    </div>`).join("");
  $("#plan-forms").querySelectorAll("input").forEach((inp) =>
    inp.addEventListener("input", () => {
      const i = Number(inp.closest(".plan-form").dataset.i);
      const k = inp.dataset.k;
      S.plans[i][k] = k === "name" ? inp.value : parseFloat(inp.value);
      scheduleRecalc();
    })
  );
  $("#plan-forms").querySelectorAll("[data-del]").forEach((btn) =>
    btn.addEventListener("click", () => {
      const i = Number(btn.closest(".plan-form").dataset.i);
      S.plans.splice(i, 1);
      buildPlanForms();
      if (S.plans.length) {
        scheduleRecalc();
      } else {
        // 删空后清空结果，避免残留已删除计划的数据
        clearTimeout(debounceTimer);
        S.result = null;
        $("#result-body").innerHTML = `<tr><td colspan="10" class="meta">已删空计划，点「＋添加计划」开始测算</td></tr>`;
        $("#result-foot").innerHTML = "";
        $("#stability").textContent = "";
        $("#sb-total").textContent = "";
      }
    })
  );
}

$("#add-plan").addEventListener("click", () => {
  // 默认值来自服务端 param_defaults（G4 契约），不硬编码
  S.plans.push({ name: `计划${S.plans.length + 1}`, ...S.state.param_defaults });
  buildPlanForms();
  scheduleRecalc();
});

function render() {
  if (!S.result) return;
  const sc = S.result.scenarios[S.current];
  if (!sc) return;
  $("#result-body").innerHTML = sc.plans.map((p) => {
    const stab = S.result.stability ? S.result.stability[p.name] : null;
    const flip = stab && !stab.stable ? ` <span class="chip" title="跨情景结论翻转：${Object.entries(stab.verdicts).map(([k, v]) => `${k}${v === "净贡献为正" ? "✓" : "✗"}`).join(" ")}">翻转</span>` : "";
    return `
    <tr class="${p.below_breakeven ? "below" : ""}">
      <td>${esc(p.name)}${flip}</td>
      <td>${yuan(p.spend)}</td>
      <td>${num(p.clicks)}</td>
      <td>${num(p.orders)}</td>
      <td>${yuan(p.gmv)}</td>
      <td>${p.roi.toFixed(2)}</td>
      <td class="${p.net >= 0 ? "pos" : "neg"}">${yuan(p.net)}</td>
      <td>${pct(p.cvr_star)}</td>
      <td class="${p.gap > 0 ? "neg" : "pos"}">${pct(p.gap)}</td>
      <td><span class="chip ${p.net >= 0 ? "ok" : "fail"}">${esc(p.verdict)}</span></td>
    </tr>`;
  }).join("");
  $("#result-foot").innerHTML = `
    <tr><td>合计 / 加权</td><td>${yuan(sc.totals.spend)}</td><td colspan="3"></td>
        <td>${(sc.totals.gmv / sc.totals.spend).toFixed(2)}</td>
        <td class="${sc.totals.net >= 0 ? "pos" : "neg"}">${yuan(sc.totals.net)}</td><td colspan="3"></td></tr>`;
  const verdicts = Object.entries(S.result.scenarios).map(([n, s]) => {
    const wins = s.plans.filter((p) => p.net > 0).length;
    return `${n}：${wins}/${s.plans.length} 计划净贡献为正`;
  });
  $("#stability").textContent = `净贡献排名（${esc(S.current)}）：${sc.ranking.join(" > ")} ｜ ${verdicts.join(" ｜ ")}`;
  $("#sb-total").textContent = `${esc(S.current)}情景合计消耗 ${yuan(sc.totals.spend)} · 净贡献 ${yuan(sc.totals.net)}`;
}

boot().catch((e) => {
  document.body.innerHTML = `<p style="color:#b91c1c;padding:2rem">加载失败：${esc(e.message)}</p>`;
});
