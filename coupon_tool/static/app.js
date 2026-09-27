/* 优惠券测算工作台前端（无框架、离线）。状态在本页内：scenario / comparison / stress。 */
"use strict";

const S = { scenario: null, comparison: null, stress: null, selected: null, runs: [], imported: null };

const $ = (id) => document.getElementById(id);
const yuan = (cents) => (cents == null ? "—" : (cents / 100).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const pct = (v, d = 4) => (v == null ? "—" : (v * 100).toFixed(d) + "%");
const num = (v, d = 2) => (v == null ? "—" : Number(v).toLocaleString("zh-CN", { maximumFractionDigits: d }));

async function api(path, body, method) {
  const opt = body !== undefined
    ? { method: method || "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  // 相对路径：壳内（/t/coupon/）与独立运行（/）下都解析到本工具 API
  const res = await fetch(path.replace(/^\//, ""), opt);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.add("hidden"), 3200);
}

function chip(text, kind) { return `<span class="chip chip-${kind}">${text}</span>`; }
function conclusionChip(t) {
  return { feasible: chip("可行候选", "ok"), needs_validation: chip("需小范围验证", "warn"),
           no_feasible_coupon: chip("建议不发券", "warn"), invalid_comparison: chip("无法形成有效比较", "fail") }[t] || chip(t, "run");
}

/* ---------------- 视图切换 ---------------- */
const VIEW_META = {
  data: ["数据与基准", "导入基准分布、确认口径；或直接加载演示场景"],
  params: ["场景与参数", "候选、成本、行为与约束——每个参数都要有来源"],
  compare: ["比较与决策", "同一账本的同口径比较；允许“不发券”成为结论"],
  history: ["历史与复盘", "运行不可变；重放可复核；复盘不覆盖历史"],
};
document.querySelectorAll("#nav .stage").forEach((btn) => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});
function switchView(view) {
  document.querySelectorAll("#nav .stage").forEach((b) => b.classList.toggle("current", b.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  $("view-" + view).classList.remove("hidden");
  $("view-title").textContent = VIEW_META[view][0];
  $("view-hint").textContent = VIEW_META[view][1];
  if (view === "history") loadRuns();
}

/* ---------------- Inspector ---------------- */
document.querySelectorAll(".insp-tabs .tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".insp-tabs .tab").forEach((t) => t.classList.toggle("current", t === tab));
    $("insp-caliber").classList.toggle("hidden", tab.dataset.tab !== "caliber");
    $("insp-limits").classList.toggle("hidden", tab.dataset.tab !== "limits");
  });
});
function renderLimits(limits, evidence) {
  const parts = [];
  if (evidence) parts.push(`<div class="accent-card">证据状态：${evidence}</div>`);
  (limits || []).forEach((l) => parts.push(`<div class="warn-card">${l}</div>`));
  $("insp-limits-content").innerHTML = parts.join("") || "（尚无测算结果）";
}

/* ---------------- ① 数据与基准 ---------------- */
function parseCsv(text) {
  const lines = text.trim().split(/\r?\n/).filter((l) => l.trim());
  if (!lines.length) return [];
  const header = lines[0].split(",").map((h) => h.trim());
  return lines.slice(1).map((line) => {
    const cells = line.split(",").map((c) => c.trim());
    const row = {};
    header.forEach((h, i) => { row[h] = cells[i] === "" ? null : cells[i]; });
    return row;
  });
}
$("btn-import").addEventListener("click", async () => {
  const rows = parseCsv($("import-csv").value);
  if (!rows.length) { toast("请先粘贴 CSV 数据"); return; }
  try {
    const out = await api("api/import", { mode: $("import-mode").value, rows, meta: {} });
    S.imported = out;
    const errs = out.issues.filter((i) => i.level === "error");
    const warns = out.issues.filter((i) => i.level === "warning");
    $("import-issues").innerHTML =
      (errs.length ? `<div class="fail-card">错误（必须修复）：${errs.map((e) => e.message).join("；")}</div>` : "") +
      (warns.length ? `<div class="warn-card">警告：${warns.map((w) => w.message).join("；")}</div>` : "") +
      (!out.issues.length ? `<div class="accent-card">质量检查通过（${out.row_count} 行）</div>` : "");
    $("import-preview").innerHTML = `<table class="tbl"><thead><tr><th>篮子</th><th>金额 分</th><th>权重</th><th>毛利率</th></tr></thead><tbody>` +
      out.baskets.map((b) => `<tr><td>${b.label}</td><td class="num">${num(b.amount_cents, 0)}</td><td class="num">${num(b.weight, 6)}</td><td class="num">${b.margin_rate ?? "—"}</td></tr>`).join("") +
      `</tbody></table>`;
    $("btn-apply-baseline").disabled = !!errs.length;
  } catch (e) { toast(e.message); }
});
$("btn-apply-baseline").addEventListener("click", () => {
  if (!S.imported || !S.scenario) { if (!S.scenario) { newScenario(); } }
  const sc = S.scenario;
  sc.baseline.baskets = S.imported.baskets;
  sc.baseline.data_snapshot_id = "workbench-import-" + new Date().toISOString().slice(0, 10);
  fillParamsForm();
  toast("已应用为当前场景基准；请到「场景与参数」确认 N 与 C₀");
  switchView("params");
});
$("btn-templates").addEventListener("click", async () => {
  try { const out = await api("api/templates"); toast(`模板已生成：${out.files.join("、")}（${out.dir}/）`); }
  catch (e) { toast(e.message); }
});

/* ---------------- 场景装载 ---------------- */
function newScenario() {
  S.scenario = {
    schema_version: "2.0", scenario_id: "scenario-" + Date.now().toString(36),
    currency: "CNY", observation_unit: "unique_visitor_first_paid_order", window: { type: "fixed_activity_window" },
    baseline: { visitors: null, conversion_rate: 0.08, baskets: [], data_snapshot_id: null },
    candidates: [{ enabled: false, threshold_cents: null, face_value_cents: 0, label: "无券" }],
    cost: { margin_base_rate: 0.3, margin_addon_rate: 0.3, merchant_share_rho: 1.0, fixed_fee_cents: 0, fee_rate: 0, fee_basis: "customer_paid", return_adj_cents: 0, fixed_activity_cost_cents: 0 },
    behavior: { reach_base: 1.0, reach_new: 1.0, redeem_natural: 0.8, redeem_topup: 1.0, churn: 0.02, q_mode: "curve", q_curve: { q_cap: 0.8, lam: 2.2, d_ref: 0.1 }, conversion: { mode: "relative", k: 0.9, s_max: 0.5 }, new_basket: [{ label: "新增成交", weight: 1.0, amount_cents: "at_threshold", margin_rate: 0.3, redeem: 1 }] },
    constraints: { merchant_coupon_budget_cents: null, min_incremental_contribution_cents: 0, allow_controlled_loss: false },
    objective: "incremental_contribution", evidence_status: "synthetic_assumptions", parameter_sources: {},
  };
}
async function loadDemo() {
  try {
    const out = await api("api/demo", {});
    S.scenario = out.scenario;
    S.comparison = null; S.stress = null;
    fillParamsForm();
    $("st-scenario").textContent = `场景：${out.scenario_id}（合成演示）`;
    renderLimits(["演示场景参数为合成假设（synthetic_assumptions），非行业真值"], "synthetic_assumptions");
    toast("演示场景已加载——黄金案例，可在「比较与决策」运行");
    refreshState();
  } catch (e) { toast(e.message); }
}
$("btn-demo").addEventListener("click", loadDemo);
$("btn-demo2").addEventListener("click", loadDemo);

/* ---------------- ② 场景与参数 ---------------- */
function fillParamsForm() {
  const sc = S.scenario;
  if (!sc) return;
  $("params-empty").classList.add("hidden");
  $("params-body").classList.remove("hidden");
  $("p-sid").value = sc.scenario_id;
  $("p-n").value = sc.baseline.visitors ?? "";
  $("p-c0").value = sc.baseline.conversion_rate;
  $("p-evidence").value = sc.evidence_status;
  const c = sc.cost, b = sc.behavior, k = sc.constraints;
  $("p-margin").value = c.margin_base_rate; $("p-margin-add").value = c.margin_addon_rate ?? "";
  $("p-rho").value = c.merchant_share_rho; $("p-fee").value = c.fixed_fee_cents;
  $("p-feerate").value = c.fee_rate; $("p-return").value = c.return_adj_cents; $("p-k").value = c.fixed_activity_cost_cents;
  $("p-e").value = b.reach_base; $("p-enew").value = b.reach_new;
  $("p-r").value = b.redeem_natural; $("p-rp").value = b.redeem_topup; $("p-d").value = b.churn;
  $("p-qmode").value = b.q_mode;
  $("p-qcap").value = b.q_curve.q_cap; $("p-lam").value = b.q_curve.lam; $("p-dref").value = b.q_curve.d_ref;
  $("p-conv").value = b.conversion.mode; $("p-kc").value = b.conversion.k ?? ""; $("p-smax").value = b.conversion.s_max ?? "";
  $("p-dcp").value = b.conversion.delta_c_plus ?? "";
  $("p-objective").value = sc.objective;
  $("p-budget").value = k.merchant_coupon_budget_cents != null ? k.merchant_coupon_budget_cents / 100 : "";
  $("p-floor").value = k.min_incremental_contribution_cents / 100;
  $("p-loss").checked = !!k.allow_controlled_loss;
  $("p-maxloss").value = k.max_loss_cents != null ? k.max_loss_cents / 100 : "";
  $("p-mincvr").value = k.min_conversion_rate ?? "";
  $("p-maxft").value = k.max_ft_ratio ?? "";
  const srcCost = sc.parameter_sources && sc.parameter_sources["behavior.q_curve"];
  $("src-cost").textContent = "来源：" + (srcCost ? `${srcCost.source_type}｜${srcCost.note}` : "未标注");
  $("src-behavior").textContent = $("src-cost").textContent;
  renderCandTable();
}
function renderCandTable() {
  const tbody = $("cand-table").querySelector("tbody");
  tbody.innerHTML = "";
  S.scenario.candidates.forEach((cand, i) => {
    const tr = document.createElement("tr");
    if (!cand.enabled) {
      tr.innerHTML = `<td>—</td><td colspan="2">无券基准候选（始终参与）</td><td class="text3">对照</td><td></td>`;
      tbody.appendChild(tr);
      return;
    }
    tr.innerHTML = `
      <td><input type="checkbox" data-i="${i}" class="cand-en" ${cand.enabled ? "checked" : ""}></td>
      <td><input type="number" class="inp cand-t" data-i="${i}" value="${cand.threshold_cents / 100}" step="1"></td>
      <td><input type="number" class="inp cand-f" data-i="${i}" value="${cand.face_value_cents / 100}" step="1"></td>
      <td class="text3">${cand.label || ""}${cand.extrapolated ? "（外推）" : ""}</td>
      <td><button class="btn sm ghost cand-del" data-i="${i}">删除</button></td>`;
    tbody.appendChild(tr);
  });
  tbody.querySelectorAll(".cand-en").forEach((el) => el.addEventListener("change", (e) => { S.scenario.candidates[+e.target.dataset.i].enabled = e.target.checked; }));
  tbody.querySelectorAll(".cand-t").forEach((el) => el.addEventListener("change", (e) => { S.scenario.candidates[+e.target.dataset.i].threshold_cents = Math.round(+e.target.value * 100); }));
  tbody.querySelectorAll(".cand-f").forEach((el) => el.addEventListener("change", (e) => { S.scenario.candidates[+e.target.dataset.i].face_value_cents = Math.round(+e.target.value * 100); }));
  tbody.querySelectorAll(".cand-del").forEach((el) => el.addEventListener("click", (e) => { S.scenario.candidates.splice(+e.currentTarget.dataset.i, 1); renderCandTable(); }));
}
$("btn-cand-add").addEventListener("click", () => {
  S.scenario.candidates.push({ enabled: true, threshold_cents: 15900, face_value_cents: 500, label: "" });
  renderCandTable();
});
function collectParams() {
  const sc = S.scenario;
  sc.scenario_id = $("p-sid").value.trim() || sc.scenario_id;
  sc.baseline.visitors = $("p-n").value === "" ? null : +$("p-n").value;
  sc.baseline.conversion_rate = +$("p-c0").value;
  sc.evidence_status = $("p-evidence").value;
  const c = sc.cost;
  c.margin_base_rate = +$("p-margin").value;
  c.margin_addon_rate = $("p-margin-add").value === "" ? null : +$("p-margin-add").value;
  c.merchant_share_rho = +$("p-rho").value;
  c.fixed_fee_cents = +($("p-fee").value || 0);
  c.fee_rate = +($("p-feerate").value || 0);
  c.return_adj_cents = +($("p-return").value || 0);
  c.fixed_activity_cost_cents = +($("p-k").value || 0);
  const b = sc.behavior;
  b.reach_base = +$("p-e").value; b.reach_new = +$("p-enew").value;
  b.redeem_natural = +$("p-r").value; b.redeem_topup = +$("p-rp").value; b.churn = +$("p-d").value;
  b.q_mode = $("p-qmode").value;
  b.q_curve.q_cap = +$("p-qcap").value; b.q_curve.lam = +$("p-lam").value; b.q_curve.d_ref = +$("p-dref").value;
  if ($("p-conv").value === "absolute") b.conversion = { mode: "absolute", delta_c_plus: +($("p-dcp").value || 0) };
  else b.conversion = { mode: "relative", k: +$("p-kc").value, s_max: +$("p-smax").value };
  sc.objective = $("p-objective").value;
  const k = sc.constraints;
  k.merchant_coupon_budget_cents = $("p-budget").value === "" ? null : Math.round(+$("p-budget").value * 100);
  k.min_incremental_contribution_cents = Math.round(+$("p-floor").value * 100);
  k.allow_controlled_loss = $("p-loss").checked;
  k.max_loss_cents = $("p-maxloss").value === "" ? null : Math.round(+$("p-maxloss").value * 100);
  k.min_conversion_rate = $("p-mincvr").value === "" ? null : +$("p-mincvr").value;
  k.max_ft_ratio = $("p-maxft").value === "" ? null : +$("p-maxft").value;
  return sc;
}
$("btn-save-scenario").addEventListener("click", async () => {
  try {
    const sc = collectParams();
    const out = await api("api/scenario/save", { scenario: sc });
    const errs = out.validation.errors;
    $("params-validation").innerHTML = errs.length
      ? `<span class="fail-card">校验错误：${errs.join("；")}</span>`
      : `<span class="chip chip-ok">已保存且校验通过</span>${out.validation.warnings.map((w) => `<span class="chip chip-warn">${w}</span>`).join(" ")}`;
    $("st-scenario").textContent = `场景：${out.scenario_id}`;
    refreshState();
  } catch (e) { $("params-validation").innerHTML = `<span class="fail-card">${e.message}</span>`; }
});
$("btn-goto-compare").addEventListener("click", () => { collectParams(); switchView("compare"); $("compare-empty").classList.add("hidden"); $("compare-body").classList.remove("hidden"); });

/* ---------------- ③ 比较与决策 ---------------- */
$("btn-compare").addEventListener("click", async () => {
  if (!S.scenario) { toast("先加载或创建场景"); return; }
  try {
    collectParams();
    const out = await api("api/compare", { scenario: S.scenario });
    S.comparison = out;
    renderComparison();
  } catch (e) { toast(e.message); }
});
function renderComparison() {
  const cmp = S.comparison;
  const evidence = S.scenario.evidence_status;
  $("compare-conclusion").innerHTML = conclusionChip(cmp.conclusion.type) +
    `<span class="small"> ${cmp.conclusion.message}</span>`;
  const tbody = $("res-table").querySelector("tbody");
  tbody.innerHTML = "";
  const ranked = new Set(cmp.ranking);
  cmp.rows.forEach((row) => {
    const m = row.metrics;
    const tr = document.createElement("tr");
    tr.className = "clickable" + (S.selected === row.label ? " selected" : "");
    if (!m) {
      tr.innerHTML = `<td>${row.label}</td><td>${evidence}</td><td colspan="10" class="text3">不合法：${row.violations.map((v) => v.message).join("；")}</td>`;
      tbody.appendChild(tr);
      return;
    }
    const dPi = m.incremental_contribution_cents;
    tr.innerHTML = `
      <td>${row.label}${ranked.has(row.label) ? (cmp.ranking[0] === row.label ? " ⭐" : "") : ""}</td>
      <td class="text3">${evidence}</td>
      <td class="num">${pct(m.conversion_rate)}</td>
      <td class="num">${(m.delta_c * 100).toFixed(4)}</td>
      <td class="num">${pct(m.churn_rate)}</td>
      <td class="num">${num(m.new_orders)}</td>
      <td class="num">${num(m.natural_redemptions)}</td>
      <td class="num">${num(m.topup_redemptions)}</td>
      <td class="num">${yuan(m.merchant_subsidy_cents)}</td>
      <td class="num">${yuan(m.total_contribution_cents)}</td>
      <td class="num ${dPi >= 0 ? "pos" : "neg"}">${dPi >= 0 ? "+" : ""}${yuan(dPi)}</td>
      <td class="num">${m.roi == null ? "不适用" : m.roi.toFixed(4)}</td>
      <td>${row.feasible ? chip("可行", "ok") : chip(row.violations.length + " 项不满足", "fail")}</td>`;
    tr.addEventListener("click", () => { S.selected = row.label; renderComparison(); renderRowDetail(row); });
    tbody.appendChild(tr);
  });
  const filtered = cmp.rows.filter((r) => r.metrics && !r.feasible);
  $("filtered-note").textContent = filtered.length
    ? `被过滤的候选（不消失，附原因）：${filtered.map((r) => `${r.label}——${r.violations.map((v) => v.message).join("；")}`).join(" ｜ ")}`
    : "";
  renderLimits([cmp.rows.find((r) => r.label === (S.selected || cmp.ranking[0]))?.limitations || []].flat(), evidence);
  const sel = $("d-choice");
  sel.innerHTML = '<option value="">— 选择 —</option>' +
    cmp.rows.map((r) => `<option value="${r.label}">${r.label}${r.feasible ? "" : "（不可行）"}</option>`).join("") +
    '<option value="暂不发券">暂不发券</option><option value="暂不决策">暂不决策</option>';
}
function renderRowDetail(row) {
  const m = row.metrics, d = row.decomposition || {}, be = row.breakeven;
  const decompRows = [["natural_redemption", "自然核销影响"], ["topup", "加购"], ["other_retained", "其他保留成交"],
    ["lost_orders", "流失订单损失"], ["new_orders", "新增成交"], ["fixed_costs", "新增固定费用"]];
  let beHtml = "<p class='small text3'>（无券基准或不可行候选，无回本条件）</p>";
  if (be && !be.nonpositive_pi_new) {
    beHtml = `<ul class="small">
      <li>所需毛新增成交率 ΔC⁺ = <b>${pct(be.d_c_plus_be)}</b>（对应最终转化率 ${pct(be.c_be)}，净变化 ${(be.delta_c_be * 100).toFixed(4)} pp）</li>
      <li>可触达非购买者上限 ${pct(be.reachable_cap)}——${be.within_reachable_cap ? chip("未超限", "ok") : chip("超过上限：当前假设下不可回本", "fail")}</li>
      <li>该新增量商家券补 ${yuan(be.merchant_subsidy_at_be_cents)} 元，${be.budget_ok_at_be ? chip("预算内", "ok") : chip("超预算", "fail")}</li>
    </ul>`;
  } else if (be && be.nonpositive_pi_new) {
    beHtml = `<div class="warn-card">${be.note}</div>`;
  }
  $("row-detail").innerHTML = `
    <div class="card">
      <div class="card-h">${row.label} · 收益拆解（与总 ΔΠ 对平）</div>
      <table class="tbl"><thead><tr><th>来源</th><th>金额 元</th></tr></thead><tbody>
        ${decompRows.map(([k2, n2]) => `<tr><td>${n2}</td><td class="num">${yuan(d[k2] ?? 0)}</td></tr>`).join("")}
        <tr><td><b>合计（= 增量贡献）</b></td><td class="num"><b>${yuan(m.incremental_contribution_cents)}</b></td></tr>
      </tbody></table>
    </div>
    <div class="card"><div class="card-h">回本条件（需要多好才值得发）</div>${beHtml}</div>
    <div class="card">
      <div class="card-h">邻近候选与未选原因</div>
      ${row.neighbors && row.neighbors.length ? `<table class="tbl"><thead><tr><th>候选</th><th>状态</th></tr></thead><tbody>
        ${row.neighbors.map((nb) => `<tr><td>${nb.label}</td><td>${nb.feasible ? chip("可行", "ok") : chip("被过滤：" + nb.filtered_reason, "fail")}</td></tr>`).join("")}
      </tbody></table>` : "<p class='small text3'>（无相邻候选）</p>"}
    </div>
    <div class="card">
      <div class="card-h">分支账本（${row.label}）</div>
      <div class="tbl-wrap"><table class="tbl"><thead><tr>
        <th>人群</th><th>分支</th><th>概率</th><th>期望订单</th><th>券前金额 分</th><th>核销</th><th>商家券补 分</th><th>毛利 分</th><th>贡献 分</th>
      </tr></thead><tbody>
        ${(row.ledger || []).map((e) => `<tr>
          <td>${e.group}</td><td>${e.branch}</td><td class="num">${e.probability.toFixed(6)}</td>
          <td class="num">${num(e.expected_orders, 4)}</td><td class="num">${num(e.amount_cents, 0)}</td>
          <td>${e.redeemed ? "是" : "否"}</td><td class="num">${num(e.merchant_subsidy_cents, 0)}</td>
          <td class="num">${num(e.gross_margin_cents, 0)}</td><td class="num">${num(e.contribution_cents, 0)}</td>
        </tr>`).join("")}
      </tbody></table></div>
    </div>`;
  $("row-detail").scrollIntoView({ behavior: "smooth", block: "nearest" });
}
$("btn-stress").addEventListener("click", async () => {
  const variants = {};
  document.querySelectorAll(".stress-var:checked").forEach((el) => { variants[el.dataset.variant] = JSON.parse(el.dataset.changes); });
  if (!Object.keys(variants).length) { toast("先勾选至少一个情景（范围必须显式）"); return; }
  try {
    const out = await api("api/stress", { scenario: collectParams(), variants });
    S.stress = out;
    const selLabel = S.selected || (S.comparison && S.comparison.ranking[0]) || "";
    let html = `<table class="tbl"><thead><tr><th>情景</th><th>所选候选 ΔΠ 元</th><th>预算超限</th><th>排序变化</th><th>仍可行</th></tr></thead><tbody>`;
    out.scenarios.forEach((sc) => {
      const row = sc.rows.find((r) => r.label === selLabel);
      html += `<tr><td>${sc.name}</td><td class="num">${row ? yuan(row.delta_pi_cents) : "—"}</td>
        <td>${row && row.budget_exceeded ? chip("超限", "fail") : chip("未超", "ok")}</td>
        <td>${sc.ranking_changed ? chip("有变化", "warn") : chip("不变", "ok")}</td>
        <td>${row ? (row.feasible ? chip("是", "ok") : chip("否", "fail")) : "—"}</td></tr>`;
    });
    html += `</tbody></table>`;
    if (out.sensitive_params && out.sensitive_params.length) {
      html += `<p class="small">主要敏感参数：${out.sensitive_params.slice(0, 3).map((p) => `${p.param}（ΔΠ 极差 ${yuan(p.delta_pi_spread_cents)} 元）`).join("、")}</p>`;
    }
    $("stress-out").innerHTML = html;
  } catch (e) { toast(e.message); }
});
$("btn-run").addEventListener("click", async () => {
  const choice = $("d-choice").value;
  if (!choice) { toast("请先在决策卡选择（方案 / 暂不发券 / 暂不决策）"); return; }
  const variants = {};
  document.querySelectorAll(".stress-var:checked").forEach((el) => { variants[el.dataset.variant] = JSON.parse(el.dataset.changes); });
  const decision = { choice, reason: $("d-reason").value, confirmed_by: $("d-by").value, confirmed_at: new Date().toISOString() };
  try {
    const out = await api("api/run", { scenario: collectParams(), with_stress: Object.keys(variants).length > 0, variants, decision });
    $("st-run").textContent = `最近运行：${out.run_id}`;
    $("run-out").innerHTML = `<div class="accent-card">已封存运行 <span class="mono">${out.run_id}</span>（结果不可变，可重放复核）</div>
      <p class="small">导出：
        <a href="api/export/${out.run_id}/markdown" target="_blank">Markdown 决策摘要</a> ·
        <a href="api/export/${out.run_id}/csv_candidates" target="_blank">CSV 候选表</a> ·
        <a href="api/export/${out.run_id}/csv_ledger" target="_blank">CSV 分支账本</a> ·
        <a href="api/export/${out.run_id}/json" target="_blank">JSON 运行记录</a></p>`;
    toast("运行已封存并导出三格式");
    refreshState();
  } catch (e) { toast(e.message); }
});

/* ---------------- ④ 历史与复盘 ---------------- */
async function loadRuns() {
  try {
    const runs = await api("api/runs");
    S.runs = runs;
    $("runs-list").innerHTML = runs.length ? runs.map((r) => `
      <div class="file" data-run="${r.run_id}">
        <span class="grow"><span class="mono">${r.run_id}</span><br>
          <span class="small text3">${r.created_at} · ${r.scenario_id}</span></span>
        ${conclusionChip(r.conclusion)}
      </div>`).join("") : "<div class='empty'><div class='empty-ico'>—</div><div>尚无运行记录</div><span class='small text3'>在「比较与决策」封存第一次运行</span></div>";
    document.querySelectorAll(".file[data-run]").forEach((el) =>
      el.addEventListener("click", () => showRun(el.dataset.run)));
  } catch (e) { toast(e.message); }
}
async function showRun(runId) {
  try {
    const run = await api(`/api/run/${runId}`);
    const top = (run.results.ranking || [])[0];
    const topLabel = typeof top === "string" ? top : top && top.label;
    const topRow = run.results.rows.find((r) => r.label === topLabel);
    $("run-detail").innerHTML = `
      <div class="card">
        <div class="card-h">运行 <span class="mono">${run.run_id}</span></div>
        <p class="small">${run.created_at} · 场景 ${run.scenario_id} · 引擎 ${run.engine_version} · 结论 ${conclusionChip(run.results.conclusion.type)}</p>
        ${topRow ? `<p class="small">排序首选：${topRow.label}　ΔΠ=${yuan(topRow.metrics.incremental_contribution_cents)} 元　商家券补=${yuan(topRow.metrics.merchant_subsidy_cents)} 元</p>` : ""}
        <p class="small">导出：
          <a href="api/export/${run.run_id}/markdown" target="_blank">Markdown</a> ·
          <a href="api/export/${run.run_id}/csv_candidates" target="_blank">CSV 候选表</a> ·
          <a href="api/export/${run.run_id}/csv_ledger" target="_blank">CSV 账本</a> ·
          <a href="api/export/${run.run_id}/json" target="_blank">JSON</a></p>
      </div>
      <div class="card"><div class="card-h">该运行的关键假设限制</div>
        ${(topRow && topRow.limitations || []).map((l) => `<div class="warn-card">${l}</div>`).join("") || "<p class='small text3'>—</p>"}
      </div>`;
  } catch (e) { toast(e.message); }
}

async function submitReview(runId) {
  const patchText = $("rv-patch").value.trim();
  let params_patch = null;
  if (patchText) {
    const [path, value] = patchText.split("=");
    const numVal = Number(value);
    params_patch = { [path]: value !== "" && !isNaN(numVal) ? numVal : value };
  }
  const body = {
    run_id: runId,
    actuals: {
      orders: +$("rv-orders").value || null,
      gmv_pre_cents: +$("rv-gmv").value || null,
      gmv_paid_cents: +$("rv-paid").value || null,
      merchant_subsidy_cents: +$("rv-subsidy").value || null,
      redemptions: +$("rv-redempt").value || null,
      window: $("rv-window").value,
      refund_handling: $("rv-refund").value || null,
    },
    notes: { [$("rv-cat").value]: $("rv-note").value },
    confirmed_by: $("rv-by").value,
    params_patch,
  };
  try {
    const out = await api("api/review", body);
    const rv = out.review;
    $("rv-out").innerHTML = `
      <div class="accent-card">预测基准：<b>${rv.selected_label}</b>（来源：${{explicit: "显式指定", decision: "人工决策记录", ranking_default: "排序第一（默认）"}[rv.chosen_source] || rv.chosen_source}）</div>
      ${rv.caliber_checks.map((c) => `<div class="warn-card">口径核查：${c}</div>`).join("")}
      <table class="tbl"><thead><tr><th>指标</th><th>预测</th><th>实际</th><th>差异</th><th>相对</th></tr></thead><tbody>
        ${rv.diffs.map((d) => `<tr><td>${d.metric_label}</td><td class="num">${num(d.predicted, 0)}</td>
          <td class="num">${num(d.actual, 0)}</td><td class="num ${d.diff >= 0 ? "pos" : "neg"}">${num(d.diff, 0)}</td>
          <td class="num">${d.pct == null ? "—" : (d.pct * 100).toFixed(2) + "%"}</td></tr>`).join("")}
      </tbody></table>
      ${rv.parameter_new_version ? `<div class="accent-card">参数新版本：<b>${rv.parameter_new_version.scenario_id}</b>（确认人 ${rv.parameter_new_version.confirmed_by || "未署名"}；原版本保留）</div>` : ""}
      <div class="warn-card">描述性对比，非因果结论${rv.causal_claim ? "" : "（未识别真实增量）"}</div>`;
    toast("复盘已保存（不覆盖历史）");
    refreshState();
  } catch (e) { toast(e.message); }
}
window.submitReview = submitReview;

/* ---------------- 启动 ---------------- */
async function refreshState() {
  try {
    const st = await api("api/state");
    $("engine-ver").textContent = st.engine_version;
    $("st-dir").textContent = `数据目录 ${st.data_dir} · 导出 ${st.out_dir}`;
    if (st.runs.length) $("st-run").textContent = `最近运行：${st.runs[0].run_id}`;
  } catch (e) { /* 后端未起 */ }
}
refreshState();
