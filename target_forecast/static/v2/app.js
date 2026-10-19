/* 经营目标测算 · 正式实现（已批准 UI + 真实 plans 业务层）。
   视图结构/文案/交互以 .flow/ui/ 钉入的已批准 demo 为基线；
   演示数据层（localStorage/规则模拟 AI/页内计算）全部替换为服务端真实能力。 */
'use strict';

const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = (n, d = 1) => Number(n).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d });
const signed = (n) => (n >= 0 ? '+' : '') + num(n);
const time = (t) => new Date(t).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false });

const stages = ['目标与范围', '数据与口径', '假设与情景', '计算与比较', '保存与导出'];
const SOURCE_LABEL = { manual: '手动编辑', ai: 'AI 建议', cli: 'CLI', import: '数据导入' };

let plans = [];            // 服务端方案摘要
let plan = null;           // 当前方案（视图模型）
let preview = null;        // 当前预览（来自最近一次计算 job）
let previewJobId = null;
let previewStale = false;  // 工作稿已修改，预览来自旧内容
let view = 'home', stage = 0, scenario = '基准';
let busy = false, calcError = '', calcNotice = '';
let dirtyForm = false, trigger = null;
let pollTimer = null;
let assistantInfo = { label: '', available: false };
let assistantText = '';
let staged = [];           // 导入弹窗中已上传待应用的文件
let storageWarned = false;

const THEME_KEY = 'tf-v2-theme';
const ACTIVE_KEY = 'tf-v2-active';

/* ---------- 基础设施 ---------- */

function toast(s) { const el = $('#toast'); el.textContent = s; el.hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => { el.hidden = true; }, 3300); }
function storageStatus() {
  const el = $('#storage-warning');
  el.hidden = !storageWarned;
  if (storageWarned) el.textContent = '与本地测算服务的连接出现问题。已保存的方案与运行不受影响；请确认工作台仍在运行后继续。';
}
function onError(e) {
  if (e && e.status === 0) { storageWarned = true; storageStatus(); }
  toast((e && e.error) || '操作失败，请重试');
}
function go(v, s = 0) {
  view = v; stage = s; assistantText = ''; calcError = ''; calcNotice = '';
  render(); window.scrollTo(0, 0);
  $('#main').focus({ preventScroll: true });
  $('#sidebar').classList.remove('open'); $('.menu-toggle').setAttribute('aria-expanded', 'false');
}
function periodLabel() {
  if (preview && preview.targetMonths && preview.targetMonths.length) {
    const ms = preview.targetMonths;
    return `${ms[0]} — ${ms[ms.length - 1]}`;
  }
  if (plan && plan.data && plan.data.commonEnd) {
    const start = plan.start;
    const [y, m] = plan.data.commonEnd.split('-').map(Number);
    const endM = m + plan.months;
    const ey = y + Math.floor((endM - 1) / 12), em = ((endM - 1) % 12) + 1;
    return `${start} — ${ey}-${String(em).padStart(2, '0')}`;
  }
  return '期间待数据确认';
}

/* ---------- 数据装载 ---------- */

async function refreshPlans() {
  const out = await Api.plans();
  plans = out.plans || [];
}

async function openDetail(id, { keepPreview = false } = {}) {
  const detail = await Api.plan(id);
  plan = View.adaptPlan(detail);
  if (!keepPreview) await restorePreview(detail);
  render();
}

async function restorePreview(detail) {
  preview = null; previewJobId = null; previewStale = false;
  const done = (detail.jobs || []).find((j) => j.status === 'done');
  const running = (detail.jobs || []).find((j) => j.status === 'running');
  if (done) {
    try {
      const job = await Api.job(plan.id, done.job_id);
      if (job.result) {
        preview = View.adaptPreview(job.result, plan);
        previewJobId = done.job_id;
        previewStale = done.content_key !== detail.content_key;
      }
    } catch (e) { /* 结果读取失败不阻断工作稿 */ }
  }
  if (running) { busy = true; pollJob(plan.id, running.job_id); }
  const failed = (detail.jobs || []).find((j) => j.status === 'failed' || j.status === 'unknown');
  if (failed && !done) {
    calcError = failed.status === 'unknown'
      ? '上次计算的执行结果未知（服务可能中断过）。工作稿与已保存运行均未受影响，可重新计算。'
      : `上次计算未完成：${(failed.error && failed.error.message) || '未知原因'}。工作稿与已保存运行均已保留。`;
  }
}

async function refreshCurrent() { if (plan) await openDetail(plan.id, { keepPreview: true }); }

/* ---------- 渲染 ---------- */

function sidebar() {
  $('#plan-count').textContent = plans.length;
  $('#run-count').textContent = plans.reduce((n, p) => n + (p.runs || 0), 0);
  $('#recent').innerHTML = plans.slice(0, 4).map((x) =>
    `<button class="recent-item ${plan && plan.id === x.plan_id && view === 'work' ? 'active' : ''}" data-action="open" data-id="${esc(x.plan_id)}">${esc(x.title)}<span>${x.runs ? `已保存 ${x.runs} 次运行` : '工作稿 · 尚未运行'}</span></button>`).join('')
    || '<p class="fine" style="padding:8px 10px">从一个经营目标开始。</p>';
  document.querySelectorAll('.nav-primary .nav-item').forEach((b) => b.classList.toggle('active', b.dataset.action === view));
  const badge = $('#data-badge');
  if (plan && plan.data) {
    badge.hidden = false;
    badge.textContent = plan.data.synthetic ? '演示数据 · 非真实业务' : '本机数据';
  } else badge.hidden = true;
}

function render() {
  sidebar(); storageStatus();
  $('#breadcrumb').innerHTML = `工作空间 <span>/</span> ${view === 'home' ? '开始测算' : view === 'plans' ? '我的方案' : view === 'runs' ? '运行记录' : '经营目标测算'}`;
  if (view === 'home') home(); else if (view === 'plans') plansPage(); else if (view === 'runs') runsPage(); else work();
}

function home() {
  const p = plans[0];
  $('#main').innerHTML = `<section class="home"><div class="eyebrow"><span aria-hidden="true">◎</span> 从经营问题到可解释的目标</div><h1>下一阶段，你想达成什么目标？</h1><p class="intro">先说清业务期待，再用数据和假设一起推演。你可以直接修改方案，也可以让 AI 提出建议。</p><div class="composer"><label for="need">描述你的经营目标</label><textarea id="need" placeholder="例如：明年希望净 GMV 增长 20%，新客和复购分别需要提高多少？"></textarea><p id="need-error" class="error-message" role="alert" hidden></p><div class="composer-bottom"><span class="fine">先形成可修改的草稿，缺少的信息留待确认。</span><button class="btn primary" data-action="create">形成测算草稿 <span aria-hidden="true">→</span></button></div></div><div class="entry-links"><span class="fine">或从已有方案继续</span><button class="btn small quiet" data-action="plans">我的方案</button><button class="btn small quiet" data-action="create-from-config">从现有配置创建</button></div><div class="section-head"><h2>${p ? '继续最近的工作' : '先看一条完整的测算流程'}</h2><span class="fine">${p ? '草稿保存在本机工作区' : '示例数据 · 可自由修改'}</span></div><div class="starter"><div class="starter-icon" aria-hidden="true">↗</div><div><h3>${p ? esc(p.title) : '2027 年全渠道经营目标（示例）'}</h3><p class="fine">${p ? `${p.goal && p.goal.value ? `目标 ${num(p.goal.value / 10000, 0)} 万 · ` : ''}${p.runs} 次已保存运行` : '天猫与抖音 · 1,280 万目标 · 三档经营假设'}</p></div><button class="btn small" data-action="${p ? 'open' : 'example'}" ${p ? `data-id="${esc(p.plan_id)}"` : ''}>${p ? '继续编辑' : '新建并载入示例数据'}</button></div></section>`;
}

function header(p) {
  return `<div class="page-head"><div><div class="title-row"><h1>${esc(p.title)}</h1><span class="badge neutral">工作稿</span></div><div class="page-meta"><span>目标 ${p.goal != null ? `${num(p.goal, 0)} 万元` : '待确认'}</span><span>${periodLabel()}</span><span>${p.data ? p.data.platforms.map((x) => esc(x.name)).join(' · ') : '数据待准备'}</span><span>已保存到本机工作区 · r${p.revision}</span></div></div><div class="actions"><button class="btn small quiet" data-action="history">修改记录</button><button class="btn small" data-action="stage" data-stage="4">${p.runs.length ? '查看已保存结果' : '保存与导出'}</button></div></div><nav class="tabs" aria-label="测算工作步骤">${stages.map((s, i) => `<button class="tab ${stage === i ? 'active' : ''}" data-action="stage" data-stage="${i}" ${stage === i ? 'aria-current="step"' : ''}><span class="num">${i + 1}</span>${s}</button>`).join('')}</nav>`;
}

function work() {
  if (!plan) { view = 'home'; return render(); }
  $('#main').innerHTML = header(plan)
    + `<div class="work-content"><section class="work-main" aria-label="${stages[stage]}">${[goalPage, dataPage, assumptionsPage, comparisonPage, deliveryPage][stage](plan)}</section>${assistant(plan)}</div>`;
  if (dirtyForm) showDirtyNotice();
}

function nextButton(i, label) {
  return `<div class="section-end"><p>可以随时返回前面的步骤修改。</p><button class="btn primary" data-action="stage" data-stage="${i}">${label} →</button></div>`;
}

function goalPage(p) {
  return `<section class="block"><div class="section-head"><h2>这次测算要回答什么</h2><span class="badge">可直接修改</span></div><p class="intro">把业务期待和测算范围说清楚。目标金额是要检验的期待，不是系统承诺。</p><div class="field-grid"><div class="field wide"><label for="goal-need">业务问题与目标</label><textarea id="goal-need">${esc(p.need)}</textarea></div><div class="field wide"><label for="goal-title">方案名称</label><input id="goal-title" value="${esc(p.title)}" maxlength="80"></div><div class="field"><label for="goal-value">期望净 GMV（万元）</label><input id="goal-value" type="number" min="0.0001" step="10" value="${p.goal != null ? p.goal : ''}" placeholder="待确认" aria-describedby="goal-error"><p id="goal-error" class="error-message" role="alert" hidden></p></div><div class="field"><label for="goal-period">测算期间</label><select id="goal-period" disabled><option>${periodLabel()}</option></select><p class="field-help">目标期 = 数据共同基期末月之后连续 ${p.months} 个月，由各平台数据推导。</p></div></div>${p.provenance ? `<p class="fine" style="margin-top:10px">参数来源：config.yaml@${esc(String(p.provenance.hash).slice(0, 12))}（创建时冻结；此后以工作稿为准）</p>` : ''}<div class="actions" style="margin-top:20px"><button class="btn" data-action="save-goal">保存目标修改</button></div></section><section class="block"><h2>这份方案会交付什么</h2><ul class="check-list"><li><span class="check-icon">✓</span><div>三档假设下的月度与全年目标<p class="fine">每个结果都能回到当时的数据和假设。</p></div></li><li><span class="check-icon">✓</span><div>与经营期待的差距及关键驱动<p class="fine">区分“算术上可达到”和“业务上有证据支持”。</p></div></li><li><span class="check-icon">✓</span><div>可保存、继续修改和复盘的方案<p class="fine">修改工作稿保留旧结果，导出绑定指定运行。</p></div></li></ul></section>${nextButton(1, '准备测算数据')}`;
}

function dataPage(p) {
  const d = p.data;
  const confirmable = d ? (d.quality.confirmable || []) : [];
  const warnings = d ? (d.quality.warnings || []) : [];
  const hasUv = false; // 场视角可用性按平台 unified 是否含 UV 在导入后由引擎判定；数据页按快照口径提示
  return `<div class="section-head"><h2>准备数据，先确认可比口径</h2><span class="badge ${p.caliber ? '' : 'warn'}">${p.caliber ? '口径与覆盖已确认' : '待确认口径'}</span></div><p class="intro">支持订单明细（模式 A）与平台月度指标（模式 B）两种 xlsx 输入。文件在本机处理，原始订单不会发送给模型。</p>${d ? `<div class="data-preview"><div class="info-row"><div><h3>${esc(d.name)}</h3><p>${esc(d.period)} · ${d.platforms.length} 个平台 · ${d.rows} 条月度记录</p></div><span class="badge neutral">${esc(d.source)}</span></div><div class="table-wrap" style="margin-top:16px"><table><thead><tr><th>平台</th><th>模式</th><th>历史覆盖</th><th>数据检查</th></tr></thead><tbody>${d.platforms.map((x) => `<tr><td>${esc(x.name)}</td><td>${x.mode === 'A' ? '订单明细' : '月度指标'}</td><td>${esc(x.coverage)}</td><td class="${x.gaps.length ? 'warning-text' : 'green'}">${x.gaps.length ? `缺 ${x.gaps.length} 个月` : '✓ 覆盖完整'}</td></tr>`).join('')}</tbody></table></div>${confirmable.length || warnings.length ? `<div class="notice warning" style="margin-top:14px"><strong>需要确认的数据事项</strong><ul>${confirmable.map((i) => `<li>${esc(i.detail)}</li>`).join('')}${warnings.map((i) => `<li>${esc(i.detail)}</li>`).join('')}</ul><p class="fine">确认口径即表示你已了解以上事项；要消除请替换数据后重新确认。</p></div>` : ''}<div class="actions" style="margin-top:14px"><button class="btn small" data-action="import">替换数据</button><button class="btn small quiet" data-action="data-detail">查看检查说明</button></div></div>` : `<div class="upload-zone"><h3>还没有用于测算的数据</h3><p class="fine">选择本机 xlsx 文件导入，或从工作区目录（workspace/forecast）读取；也可以先载入合成示例走通流程。原始数据不会发送给模型。</p><div class="actions"><button class="btn primary" data-action="import">选择数据文件</button><button class="btn" data-action="load-data">载入示例数据</button></div></div>`}<section class="block"><div class="divider-label">本次采用的统计口径</div><div class="info-row"><div><h3>净 GMV</h3><p>实付金额 = 支付净额（应已扣除退款），本工具不再做退款抵减；历史与目标使用同一口径。</p></div><span class="badge neutral">主指标</span></div><div class="info-row"><div><h3>新老客与跨平台</h3><p>新客按前 365 天无购买；各平台独立计算，跨平台用户不去重。</p></div></div><div class="info-row"><div><h3>人视角作为主口径</h3><p>无 UV 时场视角显示“缺少流量数据，未启用”；商品结构仅作独立假设校验，不混用不同视角的分母。</p></div></div><label class="check-label"><input id="caliber-check" type="checkbox" ${p.caliber ? 'checked' : ''} ${d ? '' : 'disabled'}><div>我确认以上口径与数据覆盖适用于这次试算<p>${d ? '更换数据后需要重新确认。' : '请先导入数据，再确认口径。'}</p></div></label><button class="btn" data-action="confirm-caliber" ${d ? '' : 'disabled'}>保存口径确认</button></section>${nextButton(2, '形成并调整假设')}`;
}

function assumptionsPage(p) {
  return `<div class="section-head"><h2>把增长期待拆成可讨论的假设</h2><span class="badge ${p.confirmed ? '' : 'warn'}">${p.confirmed ? '已确认用于试算' : '待确认用于试算'}</span></div><p class="intro">三档情景共用同一份数据。修改任何假设后，需要重新确认再计算。</p><div class="segment" style="margin-top:20px" aria-label="选择编辑情景">${View.NAMES.map((n) => `<button data-action="scenario" data-name="${n}" class="${scenario === n ? 'active' : ''}" aria-pressed="${scenario === n}">${n}</button>`).join('')}</div><div class="table-wrap"><table><thead><tr><th>驱动因素</th><th class="numeric">${scenario}假设</th><th>依据与边界</th></tr></thead><tbody>${View.FIELD_MAP.map(([k, , label]) => `<tr><td>${label}</td><td class="numeric"><label class="sr-only" for="param-${k}">${scenario}${label}百分比</label><input id="param-${k}" type="number" step="1" min="-50" max="200" value="${p.params[scenario][k]}"> %</td><td class="detail-cell fine">${k === 'goods' ? '独立校验，不并入人视角结果' : k === 'new' ? '获客计划假设，尚非实绩' : '业务假设 · 待实际验证'}</td></tr>`).join('')}</tbody></table></div><p id="params-error" class="error-message" role="alert" hidden></p><div class="field" style="margin-top:18px"><label for="assumption-notes">假设依据与需要验证的事</label><textarea id="assumption-notes">${esc(p.notes)}</textarea></div><div class="actions" style="margin-top:15px"><button class="btn" data-action="save-params">保存${scenario}假设修改</button><span class="fine">与右侧 AI 修改进入同一份工作稿</span></div><div class="notice warning" style="margin-top:22px"><strong>采用假设 ≠ 验证假设</strong><p>试算只能回答“如果这些假设成立”。方案仍需业务资源和后续实际表现支持。</p></div><label class="check-label"><input id="assumptions-confirm" type="checkbox" ${p.confirmed ? 'checked' : ''}><div>三档假设已检查，同意用于本次试算<p>本次确认不会把业务假设标成已验证事实。</p></div></label><button class="btn" data-action="confirm-assumptions">确认用于试算</button><div id="legacy-params" style="margin-top:20px"></div>${nextButton(3, '计算并比较情景')}`;
}

function chart(p, n) {
  const r = preview.results[n];
  const max = Math.max(...r.monthly.map((x) => Math.max(x.value, x.baseline))) * 1.12 || 1;
  const h = 150, w = 620, left = 35, step = 47;
  return `<div class="chart-box"><div class="section-head"><h3>月度净 GMV · ${n}</h3><span class="fine">万元</span></div><svg viewBox="0 0 ${w} 202" role="img" aria-label="${n}情景月度净GMV，与基期比较"><title>${n}情景月度净 GMV，与基期比较；月度分布沿用输入数据。</title>${[0, .5, 1].map((v) => `<line x1="30" y1="${h - v * h + 8}" x2="615" y2="${h - v * h + 8}" stroke="var(--line)"/><text x="24" y="${h - v * h + 12}" text-anchor="end" fill="var(--muted)" font-size="10">${Math.round(v * max)}</text>`).join('')}${r.monthly.map((m, i) => `<rect x="${left + i * step}" y="${h - m.baseline / max * h + 8}" width="13" height="${m.baseline / max * h}" fill="var(--chart-light)" rx="2"/><rect x="${left + i * step + 15}" y="${h - m.value / max * h + 8}" width="13" height="${m.value / max * h}" fill="var(--chart)" rx="2"/><text x="${left + i * step + 14}" y="182" text-anchor="middle" fill="var(--muted)" font-size="11">${i + 1}月</text>`).join('')}</svg><div class="chart-legend"><span><i class="legend-dot base"></i>基期数据</span><span><i class="legend-dot"></i>本次测算</span><span>延续历史季节分布</span></div></div>`;
}

function comparisonPage(p) {
  const issues = p.readiness;
  return `<div class="section-head"><h2>比较结果，判断目标缺口</h2><span class="badge neutral">情景推演 · 非预测承诺</span></div>${issues.length ? `<div class="notice warning"><strong>计算前还需要完成 ${issues.length} 项</strong><ul>${issues.map((x) => `<li>${esc(x)}</li>`).join('')}</ul><div class="actions"><button class="btn small" data-action="stage" data-stage="${!p.data || !p.caliber ? 1 : 2}">去完善</button></div></div>` : ''}${previewStale ? '<div class="notice warning"><strong>工作稿已修改，下面仍是上一次计算。</strong><p>重新计算后才能保存当前结果；已保存的历史运行不受影响。</p></div>' : ''}${calcError ? `<div class="notice error" role="alert"><strong>本次计算未完成</strong><p>${esc(calcError)}</p><p>工作稿与已有运行均已保留，可以重新计算。</p></div>` : ''}${calcNotice ? `<div class="notice" role="status"><p>${esc(calcNotice)}</p></div>` : ''}<div class="actions" style="margin:18px 0"><button class="btn primary" data-action="calculate" ${issues.length || busy ? 'disabled' : ''}>${busy ? '正在计算…' : preview ? '重新计算三档情景' : '计算三档情景'}</button>${busy ? '<button class="btn" data-action="cancel-calc">停止计算</button><span class="busy" role="status"><i class="spinner"></i>使用当前方案的快照</span>' : '<span class="fine">同一数据 · 同一口径 · 不同假设</span>'}</div>${preview ? resultBody(p, preview) : '<div class="empty"><h2>结果会在这里出现</h2><p>计算完成后，你可以并排比较三档情景，再选择用于经营讨论的一档。</p></div>'}<details><summary>查看计算边界</summary><p class="fine">计算使用本机确定性人／场／货引擎（${esc(preview ? preview.engine : 'forecast-engine-1.1')}），是“给定假设下的情景推演”：不是统计预测、因果识别或资源优化。计算失败或停止不会写入半结果。</p></details>`;
}

function resultBody(p, r) {
  const pick = r.results[p.selected] || r.results['基准'];
  const crossNotice = pick.hasGoods
    ? `<div class="notice ${Math.abs(pick.deviation) > 5 ? 'warning' : ''}"><strong>${Math.abs(pick.deviation) > 5 ? '需复核' : '交叉校验'}：人视角与商品结构相差 ${num(Math.abs(pick.deviation))}%</strong><p>商品结构测算 ${num(pick.goods)} 万，人视角 ${num(pick.total)} 万。两组假设互相校验，不把接近视为预测准确性证明。</p></div>`
    : '<div class="notice"><strong>本次数据无商品结构（月度指标输入），货视角未启用</strong><p>人视角照常计算；接入订单明细后可获得货视角交叉校验。</p></div>';
  return `<div class="kpi-strip"><div class="kpi"><div class="label">经营期待</div><strong>${num(p.goal || 0, 0)}</strong><small>万元</small><p class="fine">本次输入的目标</p></div><div class="kpi"><div class="label">${p.selected}情景测算</div><strong>${num(pick.total)}</strong><small>万元</small><p class="fine">较基期 ${signed(pick.growth)}%</p></div><div class="kpi"><div class="label">${pick.gap >= 0 ? '高于目标' : '距目标还差'}</div><strong>${num(Math.abs(pick.gap))}</strong><small>万元</small><p class="fine">基于已采用的假设</p></div></div><div class="table-wrap"><table><thead><tr><th>讨论方案</th><th class="numeric">净 GMV · 万</th><th class="numeric">较基期</th><th class="numeric">与目标差距</th><th>选择</th></tr></thead><tbody>${View.NAMES.map((n) => { const a = r.results[n]; return `<tr class="${n === p.selected ? 'chosen' : ''}"><td>${n}${n === p.selected ? ' <span class="badge">采用</span>' : ''}</td><td class="numeric">${num(a.total)}</td><td class="numeric">${signed(a.growth)}%</td><td class="numeric ${a.gap < 0 ? 'warning-text' : 'green'}">${signed(a.gap)} 万</td><td><button class="btn small quiet" data-action="adopt" data-name="${n}" ${previewStale || busy ? 'disabled' : ''}>${n === p.selected ? '已选择' : '采用此档'}</button></td></tr>`; }).join('')}</tbody></table></div>${chart(p, p.selected)}${crossNotice}<div class="section-head"><h3>平台贡献 · ${p.selected}</h3><button class="btn small quiet" data-action="monthly">查看月度明细</button></div><div class="table-wrap"><table><thead><tr><th>平台</th><th class="numeric">基期 · 万</th><th class="numeric">新客贡献 · 万</th><th class="numeric">老客贡献 · 万</th><th class="numeric">目标 · 万</th></tr></thead><tbody>${pick.platforms.map((x) => `<tr><td>${esc(x.name)}</td><td class="numeric">${num(x.base)}</td><td class="numeric">${num(x.newGMV)}</td><td class="numeric">${num(x.oldGMV)}</td><td class="numeric">${num(x.target)}</td></tr>`).join('')}</tbody></table></div>`;
}

function deliveryPage(p) {
  const canSave = preview && !previewStale && !busy;
  return `<div class="section-head"><h2>保存这次判断，导出同一次结果</h2><span class="badge neutral">历史结果不会被覆盖</span></div><p class="intro">工作稿可以继续修改。保存时固定方案版本、数据和三档结果，之后的下载始终读取这次运行。</p><div class="divider-label">当前工作稿</div><div class="mini-stat"><span>方案状态</span><span>r${p.revision} · ${canSave ? '已有有效计算' : '需要计算'}</span></div><div class="mini-stat"><span>采用情景</span><span>${p.selected}</span></div><div class="mini-stat"><span>目标与测算</span><span>${num(p.goal || 0, 0)} 万 / ${canSave ? `${num(preview.results[p.selected].total)} 万` : '待计算'}</span></div>${!canSave ? `<div class="notice warning" style="margin-top:18px">${previewStale ? '方案已修改，请重新计算后保存。' : '还没有本次方案的计算结果。'}<div class="actions"><button class="btn small" data-action="stage" data-stage="3">返回计算与比较</button></div></div>` : ''}<div class="section-end"><p>保存会固定方案版本与运行快照。<br>相同内容不会重复生成。</p><button class="btn primary" data-action="save-run" ${canSave ? '' : 'disabled'}>保存方案与本次运行</button></div><div class="divider-label">已保存的运行 ${p.runs.length ? `· ${p.runs.length} 次` : ''}</div>${p.runs.length ? p.runs.map((x) => runRow(x)).join('') : '<div class="empty"><h3>尚未保存运行</h3><p class="fine" style="margin-top:8px">保存后可以查看快照、下载报告，或返回工作稿继续调整。</p></div>'}<div class="notice" style="margin-top:22px"><strong>报告和页面读取同一份保存结果</strong><p>导出提供 Excel 报告（.xlsx）、中间指标 CSV 包（.zip）与运行快照 JSON，三者始终来自你指定的同一次运行；导出失败可重试，重试不重新计算。</p></div>${legacySection()}`;
}

function legacySection() {
  return '<div class="divider-label">旧版产物</div><div id="legacy-list"><p class="fine">读取中…</p></div><p class="fine">旧版产物来自重构前的固定输出目录，未关联新运行，不携带输入快照与版本链。</p>';
}

async function loadLegacy() {
  const box = $('#legacy-list');
  if (!box) return;
  try {
    const out = await Api.legacyArtifacts();
    box.innerHTML = out.artifacts.length
      ? out.artifacts.map((a) => `<div class="mini-stat"><span>${esc(a.path)}</span><a class="btn small quiet" href="${Api.legacyUrl(a.path)}">下载</a></div>`).join('')
      : '<p class="fine">没有旧版产物。</p>';
  } catch { box.innerHTML = '<p class="fine">旧版产物读取失败（不影响新运行）。</p>'; }
}

async function loadLegacyParams() {
  const box = $('#legacy-params');
  if (!box) return;
  try {
    const out = await Api.assistantParamsLegacy(plan.id);
    if (!out.exists || out.error) return;
    if (!out.items.length && !out.unknown_fields.length) return;
    box.innerHTML = `<div class="divider-label">旧版助手参数</div><p class="fine">发现 workspace/forecast/assistant_params.json（重构前的调参缓存）。核对差异后可并入当前工作稿；未知字段只列明，不会静默写入。</p>${out.items.length ? `<div class="table-wrap"><table><thead><tr><th>情景</th><th>参数</th><th class="numeric">旧值</th><th class="numeric">并入值</th></tr></thead><tbody>${out.items.map((it) => `<tr><td>${esc(it.scenario)}</td><td>${esc(it.param)}</td><td class="numeric">${it.old == null ? '—' : esc(it.old)}</td><td class="numeric">${esc(it.new)}</td></tr>`).join('')}</tbody></table></div>` : ''}${out.unknown_fields.length ? `<p class="fine warning-text">未知字段（不并入）：${out.unknown_fields.map(esc).join('、')}</p>` : ''}<div class="actions" style="margin-top:10px">${out.items.length ? '<button class="btn small" data-action="merge-legacy-params">确认并入工作稿</button>' : ''}<span class="fine">并入是一次正常编辑：假设确认随之失效。</span></div>`;
  } catch { /* 无旧参数或读取失败：面板不出现，不打扰 */ }
}

function runRow(r, owner) {
  return `<div class="run-row"><div><h3>${r.id} <span class="badge neutral">${r.version}</span></h3><p class="fine">${time(r.saved)} · ${r.selected}情景 · ${r.totalWan != null ? `${num(r.totalWan)} 万` : '—'}${view === 'runs' && owner ? ` · ${esc(owner.title)}` : ''}</p></div><div class="actions"><button class="btn small" data-action="run-detail" data-run="${r.id}">查看快照</button><button class="btn small" data-action="export" data-run="${r.id}">导出结果 ↓</button></div></div>`;
}

function assistant(p) {
  const pendingList = (p.proposals || []).filter((x) => x.status === 'pending');
  const cards = pendingList.map((prop) => {
    const conflict = prop.base_revision !== p.revision;
    const labelOf = (k) => (View.FIELD_MAP.find((f) => f[1] === k) || [, , k])[2];
    return `<div class="delta"><div class="assistant-label">修改建议 · 尚未生效</div><h3>${prop.scenario}情景</h3>${prop.patches.map((pt) => `<div class="delta-row"><strong>${labelOf(pt.param)}</strong><span class="old">${num(pt.old * 100, 0)}%</span><span class="next">→ ${num(pt.new * 100, 0)}%</span></div>`).join('')}${prop.rationale ? `<p class="fine">${esc(prop.rationale)}</p>` : ''}<p class="fine">采纳后需要重新确认假设；已有运行保持原样。</p>${conflict ? '<p class="error-message">工作稿已变化，请重新生成建议，避免覆盖新修改。</p>' : ''}<div class="actions"><button class="btn small primary" data-action="accept-ai" data-id="${prop.proposal_id}" ${conflict ? 'disabled' : ''}>采纳修改</button><button class="btn small" data-action="reject-ai" data-id="${prop.proposal_id}">放弃</button></div></div>`;
  }).join('');
  const hints = ['我会先整理目标与范围。目标金额是你希望检验的经营期待；数据和增长假设需要进一步确认。', '先检查数据覆盖和口径，再形成基线。没有 UV 时，人视角也可以完整计算，不需要补造流量数据。', '可以先调整新客与复购的假设。我提出的修改会先展示差异，只有你采纳后才进入这份工作稿。', '比较三档情景与目标的距离。结果不够时，可以回到假设继续推演；不把更高的一档直接当作推荐。', '保存会保留当时的数据、假设和结果。之后即使继续编辑，旧运行的报告也不会跟着变化。'];
  return `<aside class="assistant" aria-label="测算助手"><div class="assistant-head"><span class="spark" aria-hidden="true">✧</span><h2>测算助手</h2><span class="fine">${esc(assistantInfo.label)}</span></div><div class="assistant-context">正在协助：当前工作稿 r${p.revision}<br>手动编辑与 AI 修改共用同一份方案</div><div class="assistant-message"><div class="assistant-label">${assistantText ? '给你的反馈' : '下一步建议'}</div><p>${esc(assistantText || hints[stage])}</p></div>${cards}${assistantInfo.available ? `<div class="suggestions"><button class="suggestion" data-action="suggest" data-text="把基准情景新客人数增速调整到 8%">把基准新客增速调整到 8%</button><button class="suggestion" data-action="suggest" data-text="把基准情景老客复购频次增速调整到 6%">把基准复购频次增速调整到 6%</button><button class="suggestion" data-action="suggest" data-text="解释当前目标缺口">解释当前目标缺口</button></div><div class="assistant-compose"><label for="ai-input">让助手协助调整</label><textarea id="ai-input" placeholder="例如：把挑战新客增速改为 18%"></textarea><div class="actions"><span class="fine">先看建议，再决定</span><button class="btn small" data-action="ask-ai">发送 ↑</button></div></div>` : `<p class="fine" style="margin-top:14px">助手${esc(assistantInfo.label || '未配置')}。手动流程不受影响；配置模型后可在此获得修改建议。</p>`}</aside>`;
}

function plansPage() {
  $('#main').innerHTML = `<section class="standalone"><div class="section-head"><h1>我的方案</h1><button class="btn primary" data-action="home">＋ 新建方案</button></div><p class="intro">每份方案保留一个持续编辑的工作稿，以及独立保存的版本与运行。</p>${plans.map((p) => `<div class="plan-row"><div><h2>${esc(p.title)}</h2><p class="fine">目标 ${p.goal && p.goal.value != null ? `${num(p.goal.value / 10000, 0)} 万` : '待确认'} · ${p.has_data ? '已备数据' : '数据待准备'} · ${p.runs} 次运行</p><p class="fine">最近修改 ${time(p.updated)}</p></div><button class="btn" data-action="open" data-id="${esc(p.plan_id)}">继续编辑 →</button></div>`).join('') || '<div class="empty"><h2>还没有测算方案</h2><p>从一句经营目标开始，先形成可以修改的工作稿。</p></div>'}</section>`;
}

function runsPage() {
  $('#main').innerHTML = `<section class="standalone"><h1>运行记录</h1><p class="intro">每一次保存都有独立的数据与假设快照。查看或下载历史结果，不改变当前工作稿。</p><div id="all-runs"><p class="fine">读取中…</p></div></section>`;
  Api.state().then((s) => {
    const box = $('#all-runs');
    if (!box) return;
    const runs = s.runs || [];
    box.innerHTML = runs.length
      ? runs.map((r) => runRow(View.adaptRun(r), plans.find((p) => p.plan_id === r.plan_id))).join('')
      : '<div class="empty"><h2>还没有保存的运行</h2><p>在方案中完成计算，再保存这次结果。</p><button class="btn" data-action="plans">返回我的方案</button></div>';
    box.querySelectorAll('[data-action="run-detail"],[data-action="export"]').forEach((b) => {
      b.dataset.plan = b.closest('.run-row') ? '' : '';
    });
  }).catch(() => { const box = $('#all-runs'); if (box) box.innerHTML = '<p class="fine">运行记录读取失败。</p>'; });
}

/* ---------- 弹窗 ---------- */

function modal(title, body, foot = '') {
  trigger = document.activeElement;
  $('#modal-content').innerHTML = `<div class="modal-head"><h2 id="modal-title">${title}</h2><button class="icon-btn" data-action="close-modal" aria-label="关闭弹窗">×</button></div><div class="modal-body">${body}</div>${foot ? `<div class="modal-foot">${foot}</div>` : ''}`;
  $('#modal').showModal();
}
function closeModal() { $('#modal').close(); }
function formError(id, text, input) {
  const el = $(id); el.hidden = false; el.textContent = text;
  if (input) { $(input).setAttribute('aria-invalid', 'true'); $(input).focus(); }
}

/* ---------- 导入弹窗（真实文件两阶段） ---------- */

function importDialog() {
  staged = [];
  modal('准备测算数据', `<p class="fine">支持订单明细（模式 A）与平台月度指标（模式 B）的 .xlsx 文件；数据在本机处理。也可以读取工作区目录的旧输入。</p><div class="actions"><input type="file" id="file-input" accept=".xlsx" class="sr-only"><button class="btn" data-action="pick-file">选择 xlsx 文件</button><button class="btn small quiet" data-action="workspace-list">从工作区目录选择</button></div><div id="import-staged"></div><div id="import-preview"></div><div id="import-workspace"></div>`, `<button class="btn" data-action="close-modal">取消</button><button id="apply-import" class="btn primary" data-action="apply-import" disabled>应用到当前方案</button>`);
  $('#file-input').addEventListener('change', async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try {
      const up = await Api.upload(f);
      staged.push({ ...up, platform: f.name.replace(/\.xlsx$/i, ''), mode: up.suggested_mode || 'B', mapping: {} });
      renderStaged();
    } catch (err) {
      $('#import-preview').innerHTML = `<div class="notice error" role="alert"><strong>无法读取文件</strong><p>${esc(err.error)}</p></div>`;
    }
  });
}

function renderStaged() {
  const box = $('#import-staged');
  box.innerHTML = staged.map((s, i) => `<div class="mini-stat"><span>${esc(s.filename)} · ${s.rows} 行</span><span><input class="platform-name" data-i="${i}" value="${esc(s.platform)}" aria-label="平台名称" style="width:110px"> <select class="mode-select" data-i="${i}" aria-label="输入模式"><option value="A" ${s.mode === 'A' ? 'selected' : ''}>订单明细</option><option value="B" ${s.mode === 'B' ? 'selected' : ''}>月度指标</option></select> <button class="btn small quiet" data-action="unstage" data-i="${i}">移除</button></span></div>`).join('')
    + (staged.length ? `<p class="fine" style="margin-top:8px">首行预览（${esc(staged[staged.length - 1].filename)}）：</p><div class="table-wrap"><table><thead><tr>${staged[staged.length - 1].columns.map((c) => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${staged[staged.length - 1].preview.map((row) => `<tr>${staged[staged.length - 1].columns.map((c) => `<td>${esc(row[c])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : '');
  $('#apply-import').disabled = !staged.length;
  box.querySelectorAll('.platform-name').forEach((el) => el.addEventListener('input', () => { staged[Number(el.dataset.i)].platform = el.value.trim(); }));
  box.querySelectorAll('.mode-select').forEach((el) => el.addEventListener('change', () => { staged[Number(el.dataset.i)].mode = el.value; }));
}

async function workspaceList() {
  const box = $('#import-workspace');
  try {
    const ws = await Api.workspaceSources();
    const files = [...ws.orders.map((f) => ({ f, mode: 'A' })), ...ws.metrics.map((f) => ({ f, mode: 'B' }))];
    box.innerHTML = (files.length ? `<div class="divider-label">工作区目录</div>${files.map(({ f, mode }) => `<div class="mini-stat"><span>${esc(f)}（${mode === 'A' ? '订单明细' : '月度指标'}）</span><button class="btn small" data-action="stage-workspace" data-path="${esc(f)}" data-mode="${mode}">加入</button></div>`).join('')}` : '') + (ws.conflicts.length ? `<div class="notice warning"><strong>来源冲突</strong><p>${ws.conflicts.map(esc).join('、')} 同时存在明细与月度文件；请只选择其中一种来源加入。</p></div>` : '');
  } catch (e) { box.innerHTML = `<p class="fine">工作区目录读取失败：${esc(e.error)}</p>`; }
}

/* ---------- 计算 ---------- */

async function calculate() {
  if (!plan || plan.readiness.length) return;
  busy = true; calcError = ''; calcNotice = '';
  render();
  try {
    const job = await Api.startJob(plan.id, plan.revision);
    pollJob(plan.id, job.job_id);
  } catch (e) {
    busy = false;
    calcError = e.error || '计算启动失败';
    render();
  }
}

function pollJob(pid, jid) {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(async () => {
    try {
      const job = await Api.job(pid, jid);
      if (job.status === 'running') { pollJob(pid, jid); return; }
      busy = false;
      if (job.status === 'done') {
        preview = View.adaptPreview(job.result, plan);
        previewJobId = jid;
        previewStale = job.content_key !== plan.contentKey;
        calcNotice = '三档情景已计算，尚未保存为运行';
        calcError = '';
      } else if (job.status === 'cancelled') {
        calcNotice = '你已停止本次计算，没有产生新结果。';
      } else if (job.status === 'unknown') {
        calcError = '本次计算的执行结果未知（服务可能中断过）。请重新计算；已保存运行不受影响。';
      } else {
        calcError = `计算未完成：${(job.error && job.error.message) || '未知原因'}。工作稿与已保存运行均已保留。`;
      }
      await refreshCurrent();
    } catch (e) {
      busy = false;
      calcError = e.error || '计算状态读取失败';
      render();
    }
  }, 800);
}

/* ---------- 保存与导出 ---------- */

function saveRunDialog() {
  const pick = preview.results[plan.selected];
  modal('保存方案与本次运行', `<p>将固定当前工作稿 r${plan.revision}、本次数据与三档计算结果，采用「${plan.selected}」作为讨论方案。</p><div class="notice"><strong>${num(pick.total)} 万元</strong><p>目标 ${num(plan.goal || 0, 0)} 万 · 差距 ${signed(pick.gap)} 万</p></div><p class="fine">保存后可以继续修改工作稿。旧版本与旧运行不会被覆盖。</p>`, `<button class="btn" data-action="close-modal">暂不保存</button><button class="btn primary" data-action="commit-run">确认保存</button>`);
}

async function exportDialog(runId) {
  const r = plan.runs.find((x) => x.id === runId);
  modal(`导出 ${runId} 的结果`, `<p>导出固定读取 <strong>${r.version} · ${r.id}</strong>，${r.selected}情景 ${r.totalWan != null ? `${num(r.totalWan)} 万元` : ''}。</p><div class="notice">即使当前工作稿已经修改，下面的下载仍来自这一次保存。</div><div class="actions"><button class="btn primary" data-action="download" data-kind="xlsx" data-run="${r.id}">下载 Excel 报告</button><button class="btn" data-action="download" data-kind="csv" data-run="${r.id}">下载月度 CSV 包</button><button class="btn" data-action="download" data-kind="json" data-run="${r.id}">下载快照 JSON</button></div><p class="fine" style="margin-top:18px">导出失败可重试，重试不重新计算。Excel 报告含方案版本、运行身份、口径与输入来源。</p><div id="export-status"></div>`);
}

async function downloadExport(runId, kind) {
  const box = $('#export-status');
  const url = Api.exportUrl(plan.id, runId, kind);
  try {
    if (box) box.innerHTML = '<p class="fine">正在生成…</p>';
    const res = await fetch(url);
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || `导出失败（${res.status}）`);
    }
    const blob = await res.blob();
    const dispo = res.headers.get('Content-Disposition') || '';
    const m = dispo.match(/filename\*=UTF-8''([^;]+)/);
    const name = m ? decodeURIComponent(m[1]) : `${runId}.${kind}`;
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    if (box) box.innerHTML = '<p class="fine green">已发起下载。</p>';
  } catch (e) {
    if (box) box.innerHTML = `<div class="notice error" role="alert"><strong>运行已保存，导出失败可重试</strong><p>${esc(e.message)}</p></div>`;
  }
}

async function runDetailModal(runId) {
  try {
    const d = await Api.runDetail(plan.id, runId);
    const run = d.run, snap = d.snapshot, ver = d.version;
    const total = run.summary && run.summary.selected_total != null ? run.summary.selected_total / 10000 : null;
    modal(`${run.run_id} · ${run.version} · 保存快照`, `<p><strong>${esc(ver.content.goal ? plan.title : plan.title)}</strong></p><div class="mini-stat"><span>目标 / 测算</span><strong>${ver.content.goal && ver.content.goal.value != null ? num(ver.content.goal.value / 10000, 0) : '—'} / ${total != null ? num(total) : '—'} 万</strong></div><div class="mini-stat"><span>采用情景</span><span>${run.selected}</span></div><div class="mini-stat"><span>数据</span><span>${esc(snap.synthetic ? '内置合成示例' : (snap.sources || []).map((s) => s.name).join('、'))}${snap.synthetic ? '（演示数据）' : ''}</span></div><div class="mini-stat"><span>引擎版本</span><span>${esc(run.engine_version)}</span></div><div class="mini-stat"><span>保存时间</span><span>${time(run.saved)}</span></div><div class="divider-label">保存时的假设（${run.selected}）</div>${View.FIELD_MAP.map(([k, key, label]) => { const params = (ver.content.scenarios[run.selected] || {}).params || {}; const v = key === 'tier_growth' ? (params.tier_growth || {})['爆款'] : params[key]; return `<div class="mini-stat"><span>${label}</span><span>${v != null ? num(v * 100, 0) : 0}%</span></div>`; }).join('')}<p class="fine" style="margin-top:18px">这是只读快照，查看不会改变工作稿。</p>`);
  } catch (e) { toast(e.error || '快照读取失败'); }
}

/* ---------- AI ---------- */

async function askAssistant(text) {
  if (!text) return;
  assistantText = '正在思考…';
  render();
  try {
    const out = await Api.assistantChat({ message: text, history: [], tool_id: 'forecast' });
    if (out.pending_confirmation) {
      assistantText = `${out.reply || ''}（该变更需在工作台壳的助手面板确认）`;
    } else {
      assistantText = out.reply || '（无回复）';
    }
    await refreshCurrent();  // 提案可能已由执行器落盘，刷新后出现在卡片区
  } catch (e) {
    assistantText = `助手暂不可用：${e.error}。手动流程不受影响。`;
    render();
  }
}

/* ---------- 事件 ---------- */

function showDirtyNotice() {
  if ($('#form-dirty')) return;
  $('.work-main').insertAdjacentHTML('afterbegin', `<div id="form-dirty" class="notice warning" role="status"><strong>表单有未保存修改</strong><p>保存后会进入同一份工作稿；请先保存或放弃，再切换页面或让 AI 修改。</p><div class="actions"><button class="btn small" data-action="${stage === 0 ? 'save-goal' : 'save-params'}">保存修改</button><button class="btn small quiet" data-action="discard-form">放弃表单修改</button></div></div>`);
}

document.addEventListener('input', (e) => {
  if (/^(goal-|param-)/.test(e.target.id) || e.target.id === 'assumption-notes') {
    dirtyForm = true; showDirtyNotice();
  }
});

document.addEventListener('click', async (e) => {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  const a = el.dataset.action;
  if (dirtyForm && !['save-goal', 'save-params', 'discard-form', 'theme', 'menu', 'close-modal'].includes(a)) {
    toast('请先保存或放弃表单修改，再继续操作'); return;
  }
  try {
    if (a === 'discard-form') { dirtyForm = false; render(); return; }
    if (a === 'home') go('home');
    else if (a === 'plans' || a === 'runs') { await refreshPlans(); go(a); if (a === 'runs') runsPage(); }
    else if (a === 'open') { await openDetail(el.dataset.id); localStorage.setItem(ACTIVE_KEY, el.dataset.id); go('work'); }
    else if (a === 'create') {
      const need = $('#need').value.trim();
      if (!need) { formError('#need-error', '请先说明你希望达成的经营目标。', '#need'); return; }
      const detail = await Api.createPlan(need);
      await refreshPlans();
      await openDetail(detail.draft.plan_id);
      localStorage.setItem(ACTIVE_KEY, detail.draft.plan_id);
      go('work', 0);
      toast('已形成测算草稿，请检查目标与范围');
    }
    else if (a === 'example') {
      const detail = await Api.createPlan('为天猫和抖音制定 2027 年经营目标，希望全年净 GMV 达到 1,280 万。结合去年数据，比较新客增长和老客复购的不同假设，看看目标缺口主要在哪里。', '2027 年全渠道经营目标（示例）');
      const pid = detail.draft.plan_id;
      await Api.importSynthetic(pid, 1);
      await refreshPlans();
      await openDetail(pid);
      localStorage.setItem(ACTIVE_KEY, pid);
      go('work', 1);
      toast('示例数据已载入（演示数据），请确认口径与假设');
    }
    else if (a === 'create-from-config') {
      const detail = await Api.createPlan('（从现有配置创建：参数取 config.yaml 创建时冻结值，请补充业务目标）', null, 'config');
      await refreshPlans();
      await openDetail(detail.draft.plan_id);
      localStorage.setItem(ACTIVE_KEY, detail.draft.plan_id);
      go('work', 0);
      toast('已从 config.yaml 创建方案（参数已冻结），请补充目标与数据');
    }
    else if (a === 'merge-legacy-params') {
      try {
        const out = await Api.importAssistantParams(plan.id, plan.revision);
        await openDetail(plan.id);
        render();
        toast(`已并入 ${out.merged} 项旧参数；假设确认已失效，请重新确认后计算`);
      } catch (err) {
        if (err.status === 409) toast(err.error);
        else onError(err);
      }
    }
    else if (a === 'stage') { stage = Number(el.dataset.stage); calcError = ''; calcNotice = ''; render(); window.scrollTo(0, 0); if (stage === 2) loadLegacyParams(); if (stage === 4) loadLegacy(); }
    else if (a === 'theme') {
      const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      document.documentElement.dataset.theme = theme;
      try { localStorage.setItem(THEME_KEY, theme); } catch { /* 忽略 */ }
      $('#theme-toggle').setAttribute('aria-label', theme === 'dark' ? '切换亮色主题' : '切换暗色主题');
    }
    else if (a === 'menu') { const open = $('#sidebar').classList.toggle('open'); el.setAttribute('aria-expanded', String(open)); }
    else if (a === 'close-modal') closeModal();
    else if (a === 'save-goal') {
      const goal = Number($('#goal-value').value), need = $('#goal-need').value.trim(), title = $('#goal-title').value.trim();
      if (!need || !title || !Number.isFinite(goal) || goal <= 0) {
        formError('#goal-error', '请填写方案名称、业务问题和大于 0 的目标金额。', '#goal-value'); return;
      }
      const detail = await Api.patchPlan(plan.id, plan.revision,
        { goal: { value: goal * 10000 }, need, title }, '更新目标与范围');
      dirtyForm = false;
      await openDetail(plan.id);
      previewStale = preview ? previewJobId !== null && detail.content_key !== previewKey() : previewStale;
      render();
      toast('目标已保存，已有结果保持原样');
    }
    else if (a === 'load-data') {
      await Api.importSynthetic(plan.id, plan.revision);
      await openDetail(plan.id);
      toast('示例数据已载入，请确认口径');
    }
    else if (a === 'confirm-caliber') {
      if ($('#caliber-check').checked) {
        await Api.confirm(plan.id, 'data_coverage', plan.revision);
        await Api.confirm(plan.id, 'caliber', plan.revision);
      }
      await openDetail(plan.id);
      toast(plan.caliber ? '口径与覆盖已确认' : '口径确认状态未变化');
    }
    else if (a === 'scenario') { scenario = el.dataset.name; render(); }
    else if (a === 'save-params') {
      const short = {};
      for (const [k] of View.FIELD_MAP.map((f) => [f[0]])) {
        const v = Number($(`#param-${k}`).value);
        if ($(`#param-${k}`).value === '' || !Number.isFinite(v) || v < -50 || v > 200) {
          formError('#params-error', '增速需为 -50% 至 200% 的有效数字。', `#param-${k}`); return;
        }
        short[k] = v;
      }
      await Api.patchPlan(plan.id, plan.revision,
        { scenarios: { [scenario]: { params: View.paramsPatch(short), source_type: 'manual' } },
          notes: $('#assumption-notes').value },
        `修改${scenario}情景假设`);
      dirtyForm = false;
      await openDetail(plan.id);
      toast('假设已保存，请重新确认用于试算');
    }
    else if (a === 'confirm-assumptions') {
      if ($('#assumptions-confirm').checked) await Api.confirm(plan.id, 'assumptions', plan.revision);
      await openDetail(plan.id);
      toast(plan.confirmed ? '假设已确认，可以计算' : '试算确认状态未变化');
    }
    else if (a === 'suggest') await askAssistant(el.dataset.text);
    else if (a === 'ask-ai') { const t = $('#ai-input').value.trim(); if (t) await askAssistant(t); }
    else if (a === 'accept-ai') {
      const out = await Api.applyProposal(plan.id, el.dataset.id, plan.revision);
      await openDetail(plan.id);
      assistantText = '修改已进入同一份工作稿，左侧参数与我使用的参数已同步。请确认假设后重新计算。';
      render();
      toast('已采纳修改，历史运行未改变');
    }
    else if (a === 'reject-ai') {
      await Api.discardProposal(plan.id, el.dataset.id);
      await openDetail(plan.id);
      assistantText = '已放弃建议，方案内容没有变化。';
      render();
      toast('已放弃，工作稿未修改');
    }
    else if (a === 'calculate') await calculate();
    else if (a === 'cancel-calc') {
      const running = (plan.jobs || []).find((j) => j.status === 'running');
      if (running) await Api.cancelJob(plan.id, running.job_id);
    }
    else if (a === 'adopt') {
      await Api.patchPlan(plan.id, plan.revision, { selected: el.dataset.name }, `采用${el.dataset.name}情景`);
      await openDetail(plan.id);
      render();
    }
    else if (a === 'save-run') saveRunDialog();
    else if (a === 'commit-run') {
      try {
        const out = await Api.saveRun(plan.id, previewJobId);
        closeModal();
        await refreshPlans();
        await openDetail(plan.id);
        toast(out.duplicate ? '相同内容已保存，返回已有运行' : `已保存 ${out.run.version} · ${out.run.run_id}`);
      } catch (err) {
        closeModal();
        if (err.status === 409) { toast(err.error); await openDetail(plan.id); }
        else onError(err);
      }
    }
    else if (a === 'history') {
      modal('工作稿修改记录', plan.changes.length ? plan.changes.map((c) => `<div class="timeline-item"><strong>r${c.revision} · ${esc(SOURCE_LABEL[c.source] || c.source)}</strong><p>${esc(c.description)}</p><p class="fine">${time(c.time)}</p></div>`).join('') : '<p class="fine">当前是初始草稿，还没有修改记录。</p>');
    }
    else if (a === 'data-detail') {
      modal('数据检查与口径边界', '<ul class="check-list"><li>✓ 必需字段、日期与金额有效性（问题定位到文件与行）</li><li>✓ 平台＋月份唯一，无重复月份</li><li>✓ 期间覆盖与缺月、短历史年化如实列出</li><li>✓ 同平台明细/月度双来源需显式选择</li></ul><p class="fine">通过格式与口径检查不代表已核验业务真实性。导入的源文件副本随快照保存，可复查。</p>');
    }
    else if (a === 'monthly') {
      modal(`月度明细 · ${plan.selected}`, `<p class="fine">本次计算 ${time(preview.created)} · 金额单位：万元</p><div class="table-wrap"><table><thead><tr><th>月份</th><th class="numeric">基期</th><th class="numeric">${plan.selected}测算</th></tr></thead><tbody>${preview.results[plan.selected].monthly.map((m) => `<tr><td>${m.month}</td><td class="numeric">${num(m.baseline)}</td><td class="numeric">${num(m.value)}</td></tr>`).join('')}</tbody></table></div>`);
    }
    else if (a === 'run-detail') await runDetailModal(el.dataset.run);
    else if (a === 'export') await exportDialog(el.dataset.run);
    else if (a === 'download') await downloadExport(el.dataset.run, el.dataset.kind);
    else if (a === 'import') importDialog();
    else if (a === 'pick-file') $('#file-input').click();
    else if (a === 'workspace-list') await workspaceList();
    else if (a === 'unstage') { staged.splice(Number(el.dataset.i), 1); renderStaged(); }
    else if (a === 'stage-workspace') {
      staged.push({ upload_id: null, workspace_path: el.dataset.path, filename: el.dataset.path,
                    platform: el.dataset.path.split('/').pop().replace(/\.xlsx$/i, ''),
                    mode: el.dataset.mode, mapping: {}, columns: [], preview: [], rows: 0 });
      renderStaged();
    }
    else if (a === 'apply-import') {
      if (!staged.length) return;
      const items = staged.map((s) => (s.upload_id
        ? { upload_id: s.upload_id, platform: s.platform, mode: s.mode, mapping: s.mapping }
        : { workspace_path: s.workspace_path, platform: s.platform, mode: s.mode, mapping: s.mapping }));
      try {
        await Api.importData(plan.id, plan.revision, items);
        closeModal();
        await openDetail(plan.id);
        toast('数据已导入，请确认口径与覆盖');
      } catch (err) {
        const box = $('#import-preview');
        box.innerHTML = `<div class="notice error" role="alert"><strong>数据检查未通过</strong><ul>${(err.issues && err.issues.length ? err.issues : [err.error]).map((i) => `<li>${esc(i)}</li>`).join('')}</ul></div>`;
      }
    }
  } catch (err) { onError(err); }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && $('#sidebar').classList.contains('open')) {
    $('#sidebar').classList.remove('open');
    $('.menu-toggle').setAttribute('aria-expanded', 'false');
    $('.menu-toggle').focus();
  }
});
$('#modal').addEventListener('close', () => { if (trigger && trigger.isConnected) trigger.focus(); else $('#main').focus({ preventScroll: true }); });

window.addEventListener('beforeunload', (e) => { if (dirtyForm) { e.preventDefault(); e.returnValue = ''; } });

/* ---------- 启动 ---------- */

function previewKey() {
  const j = (plan.jobs || []).find((x) => x.job_id === previewJobId);
  return j ? j.content_key : null;
}

(async function boot() {
  document.documentElement.dataset.theme = localStorage.getItem(THEME_KEY) || 'light';
  // 同源壳检测：壳托管时 /api/state 存在 → 显示“返回工作台”
  try {
    const r = await fetch('/api/state');
    if (r.ok) $('#back-shell').hidden = false;
  } catch { /* standalone */ }
  assistantInfo = await (async () => {
    const st = await Api.assistantStatus();
    if (!st) return { label: '未接入（standalone 模式无助手）', available: false };
    const label = { EchoBackend: '回放模式（非真实模型）', OpenAiCompatBackend: 'LLM 直连', PiSidecarBackend: 'pi-agent' }[st.backend] || st.backend;
    return { label, available: true };
  })();
  try {
    await refreshPlans();
    const last = localStorage.getItem(ACTIVE_KEY);
    if (last && plans.some((p) => p.plan_id === last)) await openDetail(last);
  } catch (e) { onError(e); }
  render();
  if (plan && view === 'home') { /* 保持首页，用户从最近编辑进入 */ }
})();
