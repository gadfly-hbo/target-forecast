/* 经营目标测算 v2 · API 层与服务端→视图模型适配。
   所有业务变更都经服务端 plans 层（唯一业务更新入口）；本文件不做任何业务恒等式判断，
   重复保存去重、过期拦截、确认失效一律以服务端为准，前端只呈现与即时反馈。 */
'use strict';

const Api = (() => {
  // 同源相对路径：壳内 /t/forecast/ 与 standalone / 均可工作
  const BASE = 'api/v2';

  async function req(method, path, body, raw, filename) {
    const opt = { method, headers: {} };
    if (raw !== undefined) {
      opt.headers['Content-Type'] = 'application/octet-stream';
      if (filename) opt.headers['X-Filename'] = encodeURIComponent(filename);
      opt.body = raw;
    } else if (body !== undefined) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(`${BASE}${path}`, opt);
    } catch (e) {
      throw { status: 0, error: '无法连接本地测算服务。请确认工作台仍在运行，当前内容未丢失。', code: 'network' };
    }
    let data = null;
    const ctype = res.headers.get('Content-Type') || '';
    if (ctype.includes('application/json')) data = await res.json().catch(() => null);
    if (!res.ok) {
      throw { status: res.status, error: (data && data.error) || `请求失败（${res.status}）`,
              issues: (data && data.issues) || [], code: (data && data.code) || '' };
    }
    return data;
  }

  return {
    state: () => req('GET', '/state'),
    plans: () => req('GET', '/plans'),
    plan: (id) => req('GET', `/plans/${encodeURIComponent(id)}`),
    createPlan: (need, title, source) => req('POST', '/plans', { need, title, source }),
    assistantParamsLegacy: (planId) =>
      req('GET', `/assistant-params-legacy?plan_id=${encodeURIComponent(planId)}`),
    importAssistantParams: (id, rev) =>
      req('POST', `/plans/${encodeURIComponent(id)}/import-assistant-params`, { base_revision: rev }),
    patchPlan: (id, rev, patch, description) =>
      req('POST', `/plans/${encodeURIComponent(id)}/patch`, { base_revision: rev, patch, description }),
    confirm: (id, kind, rev) =>
      req('POST', `/plans/${encodeURIComponent(id)}/confirm`, { kind, base_revision: rev }),
    upload: (file) => file.arrayBuffer().then((buf) => req('POST', '/uploads', undefined, buf, file.name)),
    importData: (id, rev, items) =>
      req('POST', `/plans/${encodeURIComponent(id)}/import`, { base_revision: rev, items }),
    importSynthetic: (id, rev) =>
      req('POST', `/plans/${encodeURIComponent(id)}/import-synthetic`, { base_revision: rev }),
    workspaceSources: () => req('GET', '/workspace-sources'),
    legacyArtifacts: () => req('GET', '/legacy-artifacts'),
    legacyUrl: (rel) => `${BASE}/legacy-artifacts/${encodeURIComponent(rel)}`,
    startJob: (id, rev) => req('POST', `/plans/${encodeURIComponent(id)}/jobs`, { base_revision: rev }),
    job: (pid, jid) => req('GET', `/plans/${encodeURIComponent(pid)}/jobs/${encodeURIComponent(jid)}`),
    cancelJob: (pid, jid) => req('POST', `/plans/${encodeURIComponent(pid)}/jobs/${encodeURIComponent(jid)}/cancel`, {}),
    saveRun: (pid, jid) => req('POST', `/plans/${encodeURIComponent(pid)}/runs`, { job_id: jid }),
    runDetail: (pid, rid) => req('GET', `/plans/${encodeURIComponent(pid)}/runs/${encodeURIComponent(rid)}`),
    exportUrl: (pid, rid, fmt) =>
      `${BASE}/plans/${encodeURIComponent(pid)}/runs/${encodeURIComponent(rid)}/export/${fmt}`,
    propose: (pid, scenario, patches, rationale, rev) =>
      req('POST', `/plans/${encodeURIComponent(pid)}/proposals`,
          { scenario, patches, rationale, base_revision: rev }),
    applyProposal: (pid, prid, rev) =>
      req('POST', `/plans/${encodeURIComponent(pid)}/proposals/${encodeURIComponent(prid)}/apply`,
          { base_revision: rev }),
    discardProposal: (pid, prid) =>
      req('POST', `/plans/${encodeURIComponent(pid)}/proposals/${encodeURIComponent(prid)}/discard`, {}),
    // 壳级助手端点（绝对路径）：standalone 模式不存在 → 面板如实降级
    assistantStatus: () => fetch('/api/assistant/status').then((r) => (r.ok ? r.json() : null)).catch(() => null),
    assistantChat: (payload) => fetch('/api/assistant/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    }).then(async (r) => {
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw { status: r.status, error: data.error || data.setup_hint || `助手请求失败（${r.status}）` };
      return data;
    }),
  };
})();

/* ---------- 服务端对象 → 已批准 UI 的视图模型 ---------- */

const View = (() => {
  const NAMES = ['保守', '基准', '挑战'];
  // 展示键 → 引擎参数键（person 五驱动 + 商品结构；场驱动 UV 参数在引擎内随数据生效，界面只读）
  const FIELD_MAP = [
    ['new', 'new_customers_growth', '新客人数增速'],
    ['value', 'new_arpu_growth', '新客人均产出增速'],
    ['old', 'old_customers_growth', '老客月活增速'],
    ['freq', 'old_freq_growth', '老客复购频次增速'],
    ['aov', 'old_aov_growth', '老客客单增速'],
    ['goods', 'tier_growth', '商品结构增速'],
  ];
  const WAN = 10000;

  function paramsOf(draft) {
    const out = {};
    for (const n of NAMES) {
      const src = (draft.scenarios[n] || {}).params || {};
      out[n] = {};
      for (const [short, key] of FIELD_MAP) {
        const v = key === 'tier_growth' ? (src.tier_growth || {})['爆款'] : src[key];
        out[n][short] = v == null ? 0 : v * 100;
      }
    }
    return out;
  }

  /** 视图参数（%，short 键）→ 服务端 patch（小数，引擎键；goods 同速写入四个梯队） */
  function paramsPatch(shortParams) {
    const params = {};
    for (const [short, key] of FIELD_MAP) {
      const v = Number(shortParams[short]) / 100;
      if (key === 'tier_growth') {
        params.tier_growth = { '爆款': v, '腰部': v, '尾部': v, '新品': v };
      } else params[key] = v;
    }
    return params;
  }

  function nextMonth(commonEnd) {
    if (!commonEnd) return null;
    const [y, m] = commonEnd.split('-').map(Number);
    return m === 12 ? `${y + 1}-01` : `${y}-${String(m + 1).padStart(2, '0')}`;
  }

  function adaptSnapshot(snap) {
    const platforms = Object.entries(snap.platforms).map(([name, m]) => ({
      name, mode: m.mode, months: m.months,
      coverage: `${m.history_start} — ${m.history_end} · ${m.months} 个月`,
      gaps: [...(m.coverage.missing_months || []), ...(m.coverage.trailing_gap || [])],
    }));
    return {
      name: snap.synthetic ? '内置合成示例数据' : (snap.sources.map((s) => s.name).join('、') || '导入数据'),
      source: snap.synthetic ? '合成演示' : '本机导入',
      synthetic: !!snap.synthetic,
      period: platforms.length ? `${snap.platforms[platforms[0]?.name]?.history_start || ''} — ${snap.common_end}` : '',
      rows: platforms.reduce((n, p) => n + p.months, 0),
      platforms,
      quality: snap.quality,
      commonEnd: snap.common_end,
      caliberFrozen: snap.caliber_frozen,
    };
  }

  function adaptRun(r) {
    const total = r.summary && r.summary.selected_total != null ? r.summary.selected_total / WAN : null;
    return { id: r.run_id, version: r.version, saved: r.saved, selected: r.selected,
             engine: r.engine_version, contentKey: r.content_key, summary: r.summary, totalWan: total };
  }

  /** 草稿详情 → 视图方案 */
  function adaptPlan(detail) {
    const d = detail.draft;
    const snap = detail.snapshot ? adaptSnapshot(detail.snapshot) : null;
    return {
      id: d.plan_id, title: d.title, need: d.need,
      goal: d.goal && d.goal.value != null ? d.goal.value / WAN : null,
      start: snap ? nextMonth(snap.commonEnd) : null,
      months: d.period.target_months,
      scope: (d.scope.platforms || []).join('、'),
      revision: d.revision, selected: d.selected, notes: d.notes || '',
      params: paramsOf(d),
      caliber: detail.confirmation_status.data_coverage.confirmed
               && detail.confirmation_status.caliber.confirmed,
      confirmed: detail.confirmation_status.assumptions.confirmed,
      confirmStatus: detail.confirmation_status,
      changes: d.changes || [],
      versions: detail.versions || [],
      runs: (detail.runs || []).map(adaptRun),
      data: snap,
      readiness: detail.readiness || [],
      contentKey: detail.content_key,
      proposals: detail.proposals || [],
      jobs: detail.jobs || [],
      provenance: d.provenance,
    };
  }

  /** 计算结果 → 预览（与已批准 UI 的 preview 结构一致；金额单位万元） */
  function adaptPreview(result, plan) {
    const rows = result.views.consolidated;
    const baseAnnual = Object.values(result.platforms)
      .reduce((s, r) => s + ((r.baseline && r.baseline.annual_gmv) || 0), 0);
    const results = {};
    for (const n of NAMES) {
      const mine = rows.filter((r) => r.scenario === n);
      const total = mine.reduce((s, r) => s + (r.GMV_主口径 || 0), 0) / WAN;
      const monthly = mine.map((r) => {
        const cal = r.month.slice(5, 7).replace(/^0/, '');
        const baseline = Object.values(result.platforms).reduce(
          (s, p) => s + (((p.baseline || {}).annual_gmv || 0) * ((p.shares || {})[cal] || 0)), 0) / WAN;
        return { month: r.month, value: (r.GMV_主口径 || 0) / WAN, baseline };
      });
      // 平台贡献：新客/老客来自人视角，目标列用该平台主口径
      const platforms = Object.entries(result.platforms).map(([name, pr]) => {
        const person = (pr.person || []).filter((r) => r.scenario === n);
        const mainRows = (pr.main_view === '场' ? pr.field || [] : pr.person || [])
          .filter((r) => r.scenario === n);
        return {
          name,
          base: ((pr.baseline || {}).annual_gmv || 0) / WAN,
          newGMV: person.reduce((s, r) => s + (r.new_gmv || 0), 0) / WAN,
          oldGMV: person.reduce((s, r) => s + (r.old_gmv || 0), 0) / WAN,
          target: mainRows.reduce((s, r) => s + (r.gmv || 0), 0) / WAN,
        };
      });
      const goods = Object.values(result.platforms)
        .flatMap((p) => p.goods || [])
        .filter((r) => r.scenario === n)
        .reduce((s, r) => s + (r.gmv || 0), 0) / WAN;
      results[n] = {
        total, growth: baseAnnual ? (total / (baseAnnual / WAN) - 1) * 100 : 0,
        gap: total - (plan.goal || 0), monthly, platforms,
        goods, hasGoods: Object.values(result.platforms).some((p) => p.goods),
        deviation: total ? (goods - total) / total * 100 : 0,
      };
    }
    return { created: result.computed_at, results, engine: result.engine_version,
             targetMonths: result.target_months, check: result.views.check,
             platformAnnual: result.views.platform_annual };
  }

  return { NAMES, FIELD_MAP, paramsOf, paramsPatch, adaptPlan, adaptPreview, adaptRun, WAN };
})();
