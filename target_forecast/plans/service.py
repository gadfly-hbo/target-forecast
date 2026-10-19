# -*- coding: utf-8 -*-
"""plans.service：经营目标测算的唯一业务更新入口。

手动编辑（HTTP）、AI 采纳（assistant 执行器）、CLI 全部调用本模块；
不允许任何第二份"当前参数"存在。对象与状态约束见 .flow/prd.md D1/D2 与 G1–G18。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import time
import warnings
from pathlib import Path

import pandas as pd
import yaml

from .. import ingest_agg, ingest_detail, pipeline
from . import models, store
from .store import ConflictError, NotFoundError  # re-export：上层统一捕获

# ---------- 常量 ----------

PERSON_KEYS = ("new_customers_growth", "new_arpu_growth", "old_customers_growth",
               "old_freq_growth", "old_aov_growth")
FIELD_KEYS = ("uv_growth", "cvr_growth", "aov_growth")
TIER_KEYS = ("爆款", "腰部", "尾部", "新品")
SCENARIO_NAMES = ("保守", "基准", "挑战")
GROWTH_RANGE = (-0.5, 2.0)
CONFIRM_KINDS = ("data_coverage", "caliber", "assumptions")
# ingest 期口径键：导入时冻结进数据快照（G1）；其余（baseline_months/target_months）留在草稿可编辑
INGEST_CALIBER_KEYS = ("new_customer_window_days", "tier_scope", "tier_pareto_pct",
                       "tier_tail_pct", "goods_window_months", "new_product_days")
EDITABLE_KEYS = ("title", "need", "goal", "period", "scope", "caliber", "scenarios", "selected",
                 "notes",   # 方案级假设依据（对应已批准 UI 的单个依据文本框）
                 "data")  # data 只能由 import_data 写入（界面不直接 PATCH）
MAX_CHANGES = 50


class ValidationError(Exception):
    """业务校验失败（422）：issues 为用户可读的阻断/问题清单，并随消息一并呈现。"""

    def __init__(self, message, issues=None):
        if issues:
            message = message + "：" + "；".join(str(i) for i in issues)
        super().__init__(message)
        self.issues = issues or []


class StaleError(ConflictError):
    """过期拦截（409）：提案/计算基于旧修订或旧内容，不能覆盖新修改。"""


# ---------- 配置 ----------

def _load_config(root: Path) -> dict | None:
    cfg_path = Path(root) / "config.yaml"
    if not cfg_path.is_file():
        return None
    return yaml.safe_load(cfg_path.read_text(encoding="utf-8"))


def _config_hash(root: Path) -> str | None:
    cfg_path = Path(root) / "config.yaml"
    if not cfg_path.is_file():
        return None
    return hashlib.sha256(cfg_path.read_bytes()).hexdigest()[:16]


# ---------- 草稿 ----------

def _flat_params(params: dict) -> dict:
    out = {}
    for k in PERSON_KEYS + FIELD_KEYS:
        out[k] = float((params or {}).get(k, 0.0))
    tg = (params or {}).get("tier_growth", {})
    out["tier_growth"] = {t: float(tg.get(t, 0.0)) for t in TIER_KEYS}
    return out


def _default_scenarios(cfg: dict | None) -> dict:
    src = (cfg or {}).get("scenarios", {})
    return {name: {"params": _flat_params(src.get(name, {})),
                   "source_type": "import" if cfg else "manual",
                   "note": "", "scope_note": "", "to_verify": ""}
            for name in SCENARIO_NAMES}


def _drafts_dir(root: Path) -> Path:
    return store.v2_root(root) / "plans"


def _draft_path(root: Path, plan_id: str) -> Path:
    return _drafts_dir(root) / plan_id / "draft.json"


def create_plan(root: Path, need: str, title: str | None = None,
                source: str = "manual", cfg: dict | None = None) -> dict:
    if cfg is None:
        cfg = _load_config(root)
    plan_id = f"plan-{models.today_stamp()}-{models.short_id()}"
    now = models.now_iso()
    draft = {
        "plan_id": plan_id,
        "title": (title or "").strip() or "未命名测算方案",
        "need": need or "",
        "goal": {"value": None, "unit": "元"},
        "period": {"target_months": int((cfg or {}).get("target", {}).get("months", 12))},
        "scope": {"platforms": []},
        "caliber": {"baseline_months": int((cfg or {}).get("caliber", {}).get("baseline_months", 12))},
        "scenarios": _default_scenarios(cfg),
        "selected": "基准",
        "notes": "",
        "data": {"snapshot_id": None},
        "confirmations": {k: None for k in CONFIRM_KINDS},
        "revision": 1,
        "created": now,
        "updated": now,
        "changes": [{"time": now, "source": source, "revision": 1,
                     "description": "创建方案" + ("（从现有配置导入参数）" if cfg else "")}],
        "provenance": ({"source": "config.yaml", "hash": _config_hash(root)} if cfg else None),
    }
    store.write_json(_draft_path(root, plan_id), draft)
    return draft


def load_draft(root: Path, plan_id: str) -> dict:
    return store.read_json(_draft_path(root, plan_id))


def _save_draft(root: Path, draft: dict) -> None:
    store.write_json(_draft_path(root, draft["plan_id"]), draft)


def list_plans(root: Path) -> list:
    out = []
    for d in store.list_dirs(_drafts_dir(root)):
        try:
            draft = store.read_json(d / "draft.json")
        except store.StoreError:
            continue
        runs_dir = d / "runs"
        runs = len(store.list_dirs(runs_dir)) if runs_dir.is_dir() else 0
        out.append({"plan_id": draft["plan_id"], "title": draft["title"],
                    "goal": draft["goal"], "revision": draft["revision"],
                    "updated": draft["updated"], "runs": runs,
                    "has_data": bool(draft.get("data", {}).get("snapshot_id"))})
    out.sort(key=lambda x: x["updated"], reverse=True)
    return out


def _validate_scenarios(scenarios: dict) -> None:
    for name, sc in scenarios.items():
        if name not in SCENARIO_NAMES:
            raise ValidationError(f"未知情景：{name}（仅 {('/').join(SCENARIO_NAMES)}）")
        params = sc.get("params", {})
        for k, v in params.items():
            if k == "tier_growth":
                for t, tv in v.items():
                    if t not in TIER_KEYS:
                        raise ValidationError(f"未知梯队：{t}")
                    _check_range(f"{name}·梯队增速-{t}", tv)
            elif k in PERSON_KEYS + FIELD_KEYS:
                _check_range(f"{name}·{k}", v)
            else:
                raise ValidationError(f"未知参数：{name}·{k}")


def _check_range(label: str, v) -> None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValidationError(f"{label} 必须是数值")
    if not (GROWTH_RANGE[0] <= f <= GROWTH_RANGE[1]):
        raise ValidationError(f"{label} 超出范围（{GROWTH_RANGE[0]:.0%} ~ {GROWTH_RANGE[1]:.0%}）")


def update_draft(root: Path, plan_id: str, patch: dict, base_revision: int,
                 source: str = "manual", description: str | None = None) -> dict:
    """唯一更新入口。patch 只接受 EDITABLE_KEYS；修订号不符 → ConflictError。

    任何变更都会把所有 pending 提案标记 expired（G14）；确认失效由域哈希在读侧派生。
    """
    with store.locked():
        draft = load_draft(root, plan_id)
        if draft["revision"] != base_revision:
            raise ConflictError(
                f"方案已被修改（当前 r{draft['revision']}，你基于 r{base_revision}），请刷新后重试")
        bad = set(patch) - set(EDITABLE_KEYS)
        if bad:
            raise ValidationError(f"不允许修改的字段: {sorted(bad)}")
        if "scenarios" in patch:
            merged = {**{k: dict(v) for k, v in draft["scenarios"].items()}}
            for name, sc in patch["scenarios"].items():
                base = merged.get(name, {"params": {}, "source_type": "manual",
                                         "note": "", "scope_note": "", "to_verify": ""})
                merged[name] = {**base, **sc,
                                "params": {**base.get("params", {}), **sc.get("params", {})}}
            _validate_scenarios(merged)
            patch = {**patch, "scenarios": merged}
        if "goal" in patch:
            goal = {**draft["goal"], **patch["goal"]}
            if goal.get("value") is not None:
                try:
                    goal["value"] = float(goal["value"])
                except (TypeError, ValueError):
                    raise ValidationError("目标金额必须是数值")
                if goal["value"] <= 0:
                    raise ValidationError("目标金额必须大于 0")
            patch = {**patch, "goal": goal}
        if "selected" in patch and patch["selected"] not in SCENARIO_NAMES:
            raise ValidationError(f"未知情景：{patch['selected']}")

        draft.update(patch)
        draft["revision"] += 1
        draft["updated"] = models.now_iso()
        draft["changes"] = ([{"time": draft["updated"], "source": source,
                              "revision": draft["revision"],
                              "description": description or _describe_patch(patch)}]
                            + draft["changes"])[:MAX_CHANGES]
        _save_draft(root, draft)
    _expire_pending_proposals(root, plan_id)
    return draft


def _describe_patch(patch: dict) -> str:
    labels = {"title": "方案名称", "need": "业务描述", "goal": "经营目标", "period": "测算期间",
              "scope": "平台范围", "caliber": "测算口径", "scenarios": "情景假设", "selected": "采用情景"}
    return "更新" + "、".join(labels.get(k, k) for k in patch)


# ---------- 确认与失效域 ----------

def domain_hashes(draft: dict) -> dict:
    return {
        "data_coverage": draft.get("data", {}).get("snapshot_id") or "none",
        "caliber": models.content_key(draft.get("caliber", {})),
        "assumptions": models.content_key(draft.get("scenarios", {})),
    }


def confirmation_status(draft: dict) -> dict:
    current = domain_hashes(draft)
    out = {}
    for kind in CONFIRM_KINDS:
        c = draft.get("confirmations", {}).get(kind)
        if not c:
            out[kind] = {"confirmed": False, "stale": False, "at_revision": None}
        elif c["domain_hash"] != current[kind]:
            out[kind] = {"confirmed": False, "stale": True, "at_revision": c["at_revision"]}
        else:
            out[kind] = {"confirmed": True, "stale": False, "at_revision": c["at_revision"]}
    return out


def confirm(root: Path, plan_id: str, kind: str, base_revision: int) -> dict:
    if kind not in CONFIRM_KINDS:
        raise ValidationError(f"未知确认类型：{kind}")
    with store.locked():
        draft = load_draft(root, plan_id)
        if draft["revision"] != base_revision:
            raise ConflictError(f"方案已被修改（当前 r{draft['revision']}），请刷新后重试")
        if kind == "data_coverage" and not draft.get("data", {}).get("snapshot_id"):
            raise ValidationError("请先准备本次测算数据，再确认数据口径与覆盖")
        draft["confirmations"][kind] = {"domain_hash": domain_hashes(draft)[kind],
                                        "at_revision": draft["revision"],
                                        "at": models.now_iso()}
        _save_draft(root, draft)
    return draft


def readiness(draft: dict) -> list:
    """计算前阻断清单（业务可读，顺序=用户处理顺序）。"""
    issues = []
    if not (draft.get("need") or "").strip():
        issues.append("请说明这次测算要回答的问题")
    goal = (draft.get("goal") or {}).get("value")
    if goal is None or goal <= 0:
        issues.append("目标金额必须大于 0")
    if not draft.get("data", {}).get("snapshot_id"):
        issues.append("请准备本次测算数据")
    st = confirmation_status(draft)
    if draft.get("data", {}).get("snapshot_id") and not st["data_coverage"]["confirmed"]:
        issues.append("请确认数据口径与覆盖")
    if not st["caliber"]["confirmed"]:
        issues.append("请确认测算口径")
    if not st["assumptions"]["confirmed"]:
        issues.append("请确认用于试算的假设")
    return issues


def run_content_key(draft: dict) -> str:
    """计算内容键：目标/期间/口径/情景/数据快照（不含 selected——一次计算覆盖三档，
    采用哪档是讨论选择，不改变计算结果；保存运行时记录当时选择）。"""
    return models.content_key({
        "goal": draft.get("goal"), "period": draft.get("period"),
        "caliber": draft.get("caliber"), "scenarios": draft.get("scenarios"),
        "snapshot": draft.get("data", {}).get("snapshot_id"),
    })


# ---------- AI 提案 ----------


def _proposals_dir(root: Path, plan_id: str) -> Path:
    return _drafts_dir(root) / plan_id / "proposals"


def list_proposals(root: Path, plan_id: str) -> list:
    out = []
    pdir = _proposals_dir(root, plan_id)
    if pdir.is_dir():
        for f in sorted(pdir.glob("*.json")):
            try:
                out.append(store.read_json(f))
            except store.StoreError:
                continue
    out.sort(key=lambda p: p["created"], reverse=True)
    return out


def _expire_pending_proposals(root: Path, plan_id: str) -> int:
    """draft 每次变更后，pending 提案主动过期（G14）。返回过期数。"""
    n = 0
    for p in list_proposals(root, plan_id):
        if p.get("status") == "pending":
            p["status"] = "expired"
            p["expired_at"] = models.now_iso()
            store.write_json(_proposals_dir(root, plan_id) / f"{p['proposal_id']}.json", p)
            n += 1
    return n


def propose_change(root: Path, plan_id: str, scenario: str, patches: dict,
                   rationale: str, base_revision: int) -> dict:
    """AI 提案 dry-run：计算旧值/新值/影响，持久化 AIProposal（不落业务参数）。

    提案是生命周期对象而非参数变更，落盘不违反只读语义（G2）。模型/界面只传
    proposal_id 回来；revision 校验在 apply 时由服务端完成。
    """
    draft = load_draft(root, plan_id)
    if draft["revision"] != base_revision:
        raise ConflictError(
            f"方案已被修改（当前 r{draft['revision']}，提案基于 r{base_revision}），请重新生成建议")
    if scenario not in SCENARIO_NAMES:
        raise ValidationError(f"未知情景：{scenario}")
    current = draft["scenarios"][scenario]["params"]
    items = []
    for k, new_v in (patches or {}).items():
        if k == "tier_growth":
            raise ValidationError("梯队增速请逐档单独提案（tier_growth 不支持整组替换）")
        if k not in PERSON_KEYS + FIELD_KEYS:
            raise ValidationError(f"未知参数：{k}")
        _check_range(f"{scenario}·{k}", new_v)
        items.append({"param": k, "old": current.get(k, 0.0), "new": float(new_v)})
    if not items:
        raise ValidationError("提案没有任何参数变更")
    proposal = {
        "proposal_id": models.new_id("prop"),
        "plan_id": plan_id,
        "scenario": scenario,
        "patches": items,
        "rationale": rationale or "",
        "impact": {"invalidates": ["assumptions"],
                   "note": "采纳后需要重新确认假设；已有运行保持原样"},
        "base_revision": base_revision,
        "status": "pending",
        "created": models.now_iso(),
    }
    store.write_json(_proposals_dir(root, plan_id) / f"{proposal['proposal_id']}.json", proposal)
    return proposal


def apply_proposal(root: Path, plan_id: str, proposal_id: str, base_revision: int) -> dict:
    """人工采纳：经统一更新入口落业务参数。幂等：已采纳提案重复采纳返回原结果零变更。"""
    ppath = _proposals_dir(root, plan_id) / f"{proposal_id}.json"
    proposal = store.read_json(ppath)
    if proposal["status"] == "applied":
        return {"draft": load_draft(root, plan_id), "proposal": proposal}
    if proposal["status"] != "pending":
        raise StaleError(f"提案已{ {'discarded': '放弃', 'expired': '过期'}.get(proposal['status'], '失效') }，"
                         "不能采纳；如需该修改请重新生成建议")
    draft = load_draft(root, plan_id)
    if draft["revision"] != proposal["base_revision"] or draft["revision"] != base_revision:
        proposal["status"] = "expired"
        proposal["expired_at"] = models.now_iso()
        store.write_json(ppath, proposal)
        raise StaleError("工作稿已变化，旧提案不能覆盖新修改；请重新生成建议")
    patch = {"scenarios": {proposal["scenario"]: {
        "params": {p["param"]: p["new"] for p in proposal["patches"]},
        "source_type": "ai"}}}
    desc = "采纳 AI 建议：" + "、".join(
        f"{proposal['scenario']}·{p['param']} {p['old']}→{p['new']}" for p in proposal["patches"])
    draft = update_draft(root, plan_id, patch, base_revision=base_revision,
                         source="ai", description=desc)
    # update_draft 会把 pending 提案标记 expired；本提案恢复为 applied 并记录落点修订
    proposal["status"] = "applied"
    proposal["applied_at"] = models.now_iso()
    proposal["applied_revision"] = draft["revision"]
    store.write_json(ppath, proposal)
    return {"draft": draft, "proposal": proposal}


def discard_proposal(root: Path, plan_id: str, proposal_id: str) -> dict:
    """放弃提案：零变更。幂等。"""
    ppath = _proposals_dir(root, plan_id) / f"{proposal_id}.json"
    proposal = store.read_json(ppath)
    if proposal["status"] == "discarded":
        return proposal
    if proposal["status"] == "applied":
        raise StaleError("提案已采纳，不能放弃")
    proposal["status"] = "discarded"
    proposal["discarded_at"] = models.now_iso()
    store.write_json(ppath, proposal)
    return proposal


# ---------- 数据导入与快照 ----------

_DEFAULT_INGEST_CALIBER = {"new_customer_window_days": 365, "tier_scope": "platform",
                           "tier_pareto_pct": 0.78, "tier_tail_pct": 0.20,
                           "goods_window_months": 12, "new_product_days": 90}


def _staging_dir(root: Path) -> Path:
    return store.v2_root(root) / "_staging"


def stage_upload(root: Path, filename: str, data: bytes) -> dict:
    """上传第一阶段：存字节到 _staging，返回列清单与前 5 行预览及模式建议。"""
    name = Path(filename or "").name
    if not name.lower().endswith(".xlsx"):
        raise ValidationError("仅支持 .xlsx 文件（订单明细或平台月度指标模板）")
    upload_id = models.new_id("upl")
    dest = _staging_dir(root) / upload_id / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    try:
        df = pd.read_excel(io.BytesIO(data), sheet_name=0)
    except Exception as e:
        shutil.rmtree(dest.parent, ignore_errors=True)
        raise ValidationError(f"无法解析 Excel 文件：{type(e).__name__}: {e}")
    cols = [str(c) for c in df.columns]
    miss_a = [c for c in ingest_detail.DETAIL_REQUIRED if c not in cols]
    miss_b = [c for c in ingest_agg.AGG_REQUIRED if c not in cols]
    suggested = "B" if not miss_b else ("A" if not miss_a else None)
    preview = models.sanitize(df.head(5).astype(object).where(df.notna(), None)
                              .to_dict(orient="records"))
    return {"upload_id": upload_id, "filename": name, "columns": cols,
            "preview": preview, "rows": int(len(df)),
            "suggested_mode": suggested, "missing": {"A": miss_a, "B": miss_b}}


def clean_staging(root: Path, max_age_seconds: int = 86400) -> int:
    """清理超时未应用的暂存上传。返回清理数。"""
    n, now = 0, time.time()
    d = _staging_dir(root)
    if d.is_dir():
        for sub in d.iterdir():
            if sub.is_dir() and now - sub.stat().st_mtime > max_age_seconds:
                shutil.rmtree(sub, ignore_errors=True)
                n += 1
    return n


def workspace_sources(root: Path) -> dict:
    """工作区目录的旧输入来源（只读扫描，不修改任何文件）。"""
    detail, agg = pipeline.scan_inputs(root)
    base = Path(root) / "workspace" / "forecast"
    rel = lambda d: sorted(str(p.relative_to(base)) for p in d.values())
    return {"orders": rel(detail), "metrics": rel(agg),
            "conflicts": pipeline.detect_conflicts(detail, agg)}


def _load_item_source(root: Path, item: dict) -> tuple[bytes, str, dict]:
    """返回 (字节, 展示名, 来源记录)。upload_id 或 workspace_path 二选一。"""
    if item.get("upload_id"):
        up = _staging_dir(root) / str(item["upload_id"])
        files = [p for p in up.iterdir() if p.is_file()] if up.is_dir() else []
        if not files:
            raise ValidationError("上传已过期或不存在，请重新选择文件")
        f = files[0]
        return f.read_bytes(), f.name, {"kind": "upload", "name": f.name}
    wp = str(item.get("workspace_path") or "")
    if not wp or ".." in Path(wp).parts:
        raise ValidationError("非法的工作区文件路径")
    f = Path(root) / "workspace" / "forecast" / wp
    if not f.is_file() or f.suffix.lower() != ".xlsx":
        raise ValidationError(f"工作区文件不存在或不是 xlsx：{wp}")
    return f.read_bytes(), f.name, {"kind": "workspace", "path": wp, "name": f.name}


def import_data(root: Path, plan_id: str, items: list, base_revision: int,
                source: str = "manual", synthetic: bool = False) -> dict:
    """导入第二阶段：映射 → 校验（blocker 拒绝）→ 生成数据快照 → 草稿引用新快照。

    快照内容身份 = 统一指标+货结构+映射+冻结口径+来源文件哈希；同内容去重。
    质量分级（G4）：blocker 抛 ValidationError（定位平台/行/列）；confirmable/warning 入快照。
    """
    draft = load_draft(root, plan_id)
    if draft["revision"] != base_revision:
        raise ConflictError(f"方案已被修改（当前 r{draft['revision']}），请刷新后重试")
    if not items:
        raise ValidationError("没有要导入的数据文件")
    seen = {}
    for it in items:
        p = (it.get("platform") or "").strip()
        if not p:
            raise ValidationError("每个文件都需要确认平台名称")
        if p in seen:
            raise ValidationError(f"平台「{p}」出现两次（{seen[p]} 与另一来源）；"
                                  "同一平台只能选一种来源，请先解决来源冲突")
        seen[p] = it.get("mode")

    cfg = _load_config(root) or {}
    frozen = {k: cfg.get("caliber", {}).get(k, v) for k, v in _DEFAULT_INGEST_CALIBER.items()}

    platforms, sources, warnings_out, confirmable = {}, [], [], []
    errors = []
    for it in items:
        platform = it["platform"].strip()
        mode = it.get("mode")
        if mode not in ("A", "B"):
            raise ValidationError(f"平台「{platform}」缺少输入模式（A=订单明细 / B=月度指标）")
        data, name, src = _load_item_source(root, it)
        sources.append({**src, "platform": platform,
                        "sha256": hashlib.sha256(data).hexdigest()})
        try:
            df = pd.read_excel(io.BytesIO(data), sheet_name=0,
                               dtype={"订单号": str, "用户ID": str, "商品ID": str} if mode == "A" else None)
        except Exception as e:
            raise ValidationError(f"[{platform}] 无法解析 Excel：{type(e).__name__}: {e}")
        mapping = {k: v for k, v in (it.get("mapping") or {}).items()}
        for canonical, source_col in mapping.items():
            if source_col not in df.columns:
                raise ValidationError(f"[{platform}] 映射的源列「{source_col}」不存在于文件中")
        if mapping:
            df = df.rename(columns={v: k for k, v in mapping.items()})
        try:
            if mode == "A":
                lines = ingest_detail.validate_detail_frame(df, platform)
                od = ingest_detail.classify_new(ingest_detail.order_level(lines),
                                                frozen["new_customer_window_days"])
                unified = ingest_detail.to_unified(od, platform)
                structure = ingest_detail.goods_structure(lines, frozen, lines["日期"].max())
            else:
                df = ingest_agg.validate_agg_frame(df, platform)
                with warnings.catch_warnings(record=True) as wlist:
                    warnings.simplefilter("always")
                    unified = ingest_agg.to_unified(df, platform)
                    for w in wlist:
                        warnings_out.append({"kind": "consistency", "platform": platform,
                                             "detail": str(w.message)})
                structure = None
        except ValueError as e:
            errors.append(str(e))
            continue
        platforms[platform] = {"mode": mode, "mapping": mapping, "unified": unified,
                               "structure": structure}
    if errors:
        raise ValidationError("数据检查未通过", issues=errors)

    ends = [pd.Period(v["unified"]["month"].max(), freq="M")
            for v in platforms.values() if len(v["unified"])]
    common_end = max(ends) if ends else None
    meta_platforms = {}
    for p, v in platforms.items():
        cov = pipeline._coverage(v["unified"], common_end)
        meta_platforms[p] = {"mode": v["mode"], "mapping": v["mapping"],
                             "months": int(len(v["unified"])),
                             "history_start": cov["history_start"], "history_end": cov["history_end"],
                             "coverage": cov}
        if cov["short_history"]:
            confirmable.append({"kind": "short_history", "platform": p,
                                "detail": f"历史仅 {cov['history_months']} 个月，"
                                          "基期年化将按月均×12 推算，代表性有限"})
        if cov["missing_months"]:
            confirmable.append({"kind": "missing_months", "platform": p,
                                "detail": f"历史缺月 {('、').join(cov['missing_months'])}；"
                                          "季节分布按全均值填充"})
        if cov["trailing_gap"]:
            confirmable.append({"kind": "trailing_gap", "platform": p,
                                "detail": f"数据止于 {cov['history_end']}，"
                                          f"缺口 {('、').join(cov['trailing_gap'])}；"
                                          "目标期仍与各平台对齐"})

    content = {"platforms": {p: {"mode": v["mode"], "mapping": v["mapping"],
                                 "unified": models.frame_records(v["unified"]),
                                 "structure": models.frame_records(v["structure"])}
                             for p, v in platforms.items()},
               "caliber_frozen": frozen,
               "files": [{"name": s["name"], "sha256": s["sha256"]} for s in sources]}
    snapshot_id = f"snap-{models.content_key(content)}"
    snap_dir = store.v2_root(root) / "snapshots" / snapshot_id
    if not snap_dir.is_dir():
        snapshot = {"snapshot_id": snapshot_id, "created": models.now_iso(),
                    "synthetic": bool(synthetic),
                    "sources": sources, "caliber_frozen": frozen,
                    "platforms": meta_platforms,
                    "quality": {"blockers": [], "confirmable": confirmable,
                                "warnings": warnings_out},
                    "common_end": str(common_end) if common_end is not None else None}
        store.write_json(snap_dir / "snapshot.json", snapshot)
        for p, v in platforms.items():
            store.write_json(snap_dir / f"unified_{p}.json",
                             models.frame_records(v["unified"]))
            if v["structure"] is not None:
                store.write_json(snap_dir / f"structure_{p}.json",
                                 models.frame_records(v["structure"]))
        src_dir = snap_dir / "source"
        for (it, (data, name, _)) in zip(items, [(_load_item_source(root, it)) for it in items]):
            src_dir.mkdir(parents=True, exist_ok=True)
            (src_dir / name).write_bytes(data)
    snapshot = store.read_json(snap_dir / "snapshot.json")

    draft = update_draft(root, plan_id, {"data": {"snapshot_id": snapshot_id}},
                         base_revision=base_revision, source=source,
                         description="导入数据：" + "、".join(s["name"] for s in sources))
    return {"draft": draft, "snapshot": snapshot_summary(snapshot)}


def snapshot_summary(snapshot: dict) -> dict:
    return {"snapshot_id": snapshot["snapshot_id"], "created": snapshot["created"],
            "synthetic": snapshot["synthetic"], "sources": snapshot["sources"],
            "caliber_frozen": snapshot["caliber_frozen"],
            "platforms": snapshot["platforms"], "quality": snapshot["quality"],
            "common_end": snapshot["common_end"]}


def load_snapshot(root: Path, snapshot_id: str) -> dict:
    return store.read_json(store.v2_root(root) / "snapshots" / snapshot_id / "snapshot.json")


def snapshot_platforms(root: Path, snapshot_id: str) -> dict:
    """快照 → 引擎输入（unified/structure DataFrame）。引擎只从这里读数据。"""
    snap_dir = store.v2_root(root) / "snapshots" / snapshot_id
    meta = load_snapshot(root, snapshot_id)
    out = {}
    for p, pm in meta["platforms"].items():
        unified = pd.DataFrame(store.read_json(snap_dir / f"unified_{p}.json"))
        struct_path = snap_dir / f"structure_{p}.json"
        structure = pd.DataFrame(store.read_json(struct_path)) if struct_path.is_file() else None
        out[p] = {"mode": pm["mode"], "unified": unified, "structure": structure}
    return out


# ---------- 计算任务（job）与运行（run） ----------

_JOB_CANCEL_FLAGS = {}  # (plan_id, job_id) -> threading.Event；进程内取消旗标


def _jobs_dir(root: Path, plan_id: str) -> Path:
    return _drafts_dir(root) / plan_id / "jobs"


def _runs_dir(root: Path, plan_id: str) -> Path:
    return _drafts_dir(root) / plan_id / "runs"


def _versions_dir(root: Path, plan_id: str) -> Path:
    return _drafts_dir(root) / plan_id / "versions"


def start_run(root: Path, plan_id: str, base_revision: int, sync: bool = False) -> dict:
    """开始计算：冻结当前内容键，登记 job 并异步（或同步）执行。

    准备不足 → ValidationError（readiness 清单）；修订不符 → ConflictError。
    结果关联冻结的内容键；算完时工作稿已变 → 结果仍可查看，但 save_run 会拒绝（A07）。
    """
    import threading

    from .. import engine as engine_mod

    draft = load_draft(root, plan_id)
    if draft["revision"] != base_revision:
        raise ConflictError(f"方案已被修改（当前 r{draft['revision']}），请刷新后重试")
    issues = readiness(draft)
    if issues:
        raise ValidationError("计算前还有未完成的准备", issues=issues)
    job_id = f"job-{models.today_stamp()}-{models.short_id()}"
    job = {"job_id": job_id, "plan_id": plan_id,
           "content_key": run_content_key(draft),
           "snapshot_id": draft["data"]["snapshot_id"],
           "engine_version": engine_mod.ENGINE_VERSION,
           "status": "running", "created": models.now_iso(), "finished": None,
           "error": None}
    store.write_json(_jobs_dir(root, plan_id) / job_id / "job.json", job)
    cancel = threading.Event()
    _JOB_CANCEL_FLAGS[(plan_id, job_id)] = cancel

    def _execute():
        try:
            payload = _compute_result(root, draft, cancel)
        except pipeline.JobCancelled:
            job["status"] = "cancelled"
        except Exception as e:  # noqa: BLE001 —— 失败如实记录，不假装成功
            job["status"] = "failed"
            job["error"] = {"type": type(e).__name__, "message": str(e)}
        else:
            store.write_json(_jobs_dir(root, plan_id) / job_id / "result.json", payload)
            job["status"] = "done"
        job["finished"] = models.now_iso()
        store.write_json(_jobs_dir(root, plan_id) / job_id / "job.json", job)
        _JOB_CANCEL_FLAGS.pop((plan_id, job_id), None)

    if sync:
        _execute()
    else:
        threading.Thread(target=_execute, daemon=True).start()
    return get_job(root, plan_id, job_id)


def _compute_result(root: Path, draft: dict, cancel_event) -> dict:
    """从快照与草稿构造引擎输入并计算，返回完整结果负载（sanitized）。"""
    from .. import engine as engine_mod

    snapshot_id = draft["data"]["snapshot_id"]
    snap = load_snapshot(root, snapshot_id)
    platforms = snapshot_platforms(root, snapshot_id)
    caliber = {**snap["caliber_frozen"],
               "baseline_months": draft["caliber"]["baseline_months"],
               "target_months": draft["period"]["target_months"]}
    scenarios = {name: sc["params"] for name, sc in draft["scenarios"].items()}
    results = pipeline.run_engine(platforms, scenarios, caliber,
                                  should_cancel=cancel_event.is_set)
    if cancel_event.is_set():
        raise pipeline.JobCancelled()
    views = pipeline.build_views(results)
    goal = (draft.get("goal") or {}).get("value")
    return models.sanitize({
        "engine_version": engine_mod.ENGINE_VERSION,
        "computed_at": models.now_iso(),
        "target_months": results[next(iter(results))]["target_months"] if results else [],
        "goal_value": goal,
        "platforms": {p: {"mode": r["mode"], "main_view": r["main_view"],
                          "baseline": r["baseline"], "coverage": r["coverage"],
                          "shares": {str(int(k)): float(v) for k, v in r["shares"].items()},
                          "unified": models.frame_records(r["unified"]),
                          "person": models.frame_records(r["person"]),
                          "field": models.frame_records(r["field"]),
                          "goods": models.frame_records(r["goods"])}
                      for p, r in results.items()},
        "views": {"consolidated": models.frame_records(views["consolidated"]),
                  "platform_annual": models.frame_records(views["platform_annual"]),
                  "check": models.frame_records(views["check"]),
                  "goods": models.frame_records(views["goods"])},
    })


def get_job(root: Path, plan_id: str, job_id: str) -> dict:
    job = store.read_json(_jobs_dir(root, plan_id) / job_id / "job.json")
    if job.get("status") == "done":
        rp = _jobs_dir(root, plan_id) / job_id / "result.json"
        if rp.is_file():
            job["result"] = store.read_json(rp)
    return job


def cancel_job(root: Path, plan_id: str, job_id: str) -> dict:
    """停止计算：置取消旗标；已完成/失败/取消的 job 原样返回（幂等）。"""
    job = get_job(root, plan_id, job_id)
    if job["status"] == "running":
        flag = _JOB_CANCEL_FLAGS.get((plan_id, job_id))
        if flag is not None:
            flag.set()
        else:
            # 非本进程启动的 job 无法发旗标：如实标注 unknown
            job["status"] = "unknown"
            job["error"] = {"type": "CancelAcrossProcess",
                            "message": "计算不在本进程，无法发送停止信号；请重开工作台确认状态"}
            store.write_json(_jobs_dir(root, plan_id) / job_id / "job.json", job)
    return get_job(root, plan_id, job_id)


def list_jobs(root: Path, plan_id: str) -> list:
    out = []
    for d in store.list_dirs(_jobs_dir(root, plan_id)):
        try:
            out.append(store.read_json(d / "job.json"))
        except store.StoreError:
            continue
    out.sort(key=lambda j: j["created"], reverse=True)
    return out


# ---------- 保存方案版本与运行 ----------


def _next_run_id(root: Path, plan_id: str) -> str:
    return f"RUN-{len(store.list_dirs(_runs_dir(root, plan_id))) + 1:03d}"


def _save_version(root: Path, plan_id: str, draft: dict) -> dict:
    """按草稿内容铸造不可变版本；同内容去重。采用档是讨论选择，记录在运行上而非版本。"""
    payload = {"goal": draft["goal"], "period": draft["period"], "scope": draft["scope"],
               "caliber": draft["caliber"], "scenarios": draft["scenarios"],
               "snapshot_id": draft["data"]["snapshot_id"]}
    vkey = models.content_key(payload)
    vpath = _versions_dir(root, plan_id) / f"{vkey}.json"
    try:
        return store.read_json(vpath)
    except store.NotFoundError:
        name = f"v{len(list(_versions_dir(root, plan_id).glob('*.json'))) + 1}.0" \
            if _versions_dir(root, plan_id).is_dir() else "v1.0"
        version = {"version_key": vkey, "name": name, "created": models.now_iso(),
                   "content": models.sanitize(payload)}
        store.write_json(vpath, version)
        return version


def save_run(root: Path, plan_id: str, job_id: str) -> dict:
    """保存方案版本与本次运行：内容键不符（过期）→ StaleError；同内容+同采用档重复保存 → 去重返回。"""
    job = get_job(root, plan_id, job_id)
    if job["status"] != "done":
        raise ValidationError(f"计算未完成（当前状态：{job['status']}），不能保存")
    draft = load_draft(root, plan_id)
    current_key = run_content_key(draft)
    if job["content_key"] != current_key:
        raise StaleError("工作稿已修改，本次计算结果已过期；请重新计算后保存")
    selected = draft["selected"]
    for d in store.list_dirs(_runs_dir(root, plan_id)):
        try:
            existing = store.read_json(d / "run.json")
        except store.StoreError:
            continue
        if existing.get("content_key") == current_key and existing.get("selected") == selected:
            return {"run": existing, "duplicate": True}
    version = _save_version(root, plan_id, draft)
    run_id = _next_run_id(root, plan_id)
    result = store.read_json(_jobs_dir(root, plan_id) / job_id / "result.json")
    summary = _run_summary(result, selected)
    run = {"run_id": run_id, "plan_id": plan_id,
           "version": version["name"], "version_key": version["version_key"],
           "content_key": current_key, "snapshot_id": job["snapshot_id"],
           "engine_version": job["engine_version"], "selected": selected,
           "summary": summary,
           "saved": models.now_iso(), "source_job": job_id, "exports": {}}
    run_dir = _runs_dir(root, plan_id) / run_id
    store.write_json(run_dir / "run.json", run)
    shutil.copy2(_jobs_dir(root, plan_id) / job_id / "result.json",
                 run_dir / "result.json")
    return {"run": run, "duplicate": False}


def _run_summary(result: dict, selected: str) -> dict:
    """运行记录上的轻量摘要：各档合计/增速/目标差距（列表与报告头用，不含明细）。"""
    totals: dict = {}
    for row in result.get("views", {}).get("consolidated", []):
        totals[row["scenario"]] = totals.get(row["scenario"], 0.0) + (row.get("GMV_主口径") or 0.0)
    base_total = sum((r.get("baseline") or {}).get("annual_gmv") or 0.0
                     for r in result.get("platforms", {}).values())
    goal = result.get("goal_value")
    sel_total = totals.get(selected)
    return {"scenario_totals": {k: round(v, 2) for k, v in totals.items()},
            "baseline_annual": round(base_total, 2),
            "selected_total": round(sel_total, 2) if sel_total is not None else None,
            "selected_growth": (round(sel_total / base_total - 1, 6)
                                if sel_total is not None and base_total else None),
            "gap_to_goal": (round(goal - sel_total, 2)
                            if sel_total is not None and goal is not None else None)}


def get_run(root: Path, plan_id: str, run_id: str) -> dict:
    return store.read_json(_runs_dir(root, plan_id) / run_id / "run.json")


def get_run_result(root: Path, plan_id: str, run_id: str) -> dict:
    return store.read_json(_runs_dir(root, plan_id) / run_id / "result.json")


def list_runs(root: Path, plan_id: str = None) -> list:
    out = []
    plan_dirs = ([_drafts_dir(root) / plan_id] if plan_id
                 else store.list_dirs(_drafts_dir(root)))
    for pd_ in plan_dirs:
        for d in store.list_dirs(pd_ / "runs"):
            try:
                out.append(store.read_json(d / "run.json"))
            except store.StoreError:
                continue
    out.sort(key=lambda r: r["saved"], reverse=True)
    return out


# ---------- 导出（绑定指定运行；失败可重试、不重新计算） ----------

_EXPORTERS = ("xlsx", "csv", "json")


def _rebuild_results(result: dict) -> tuple[dict, dict, dict]:
    """run result.json → report.write_report 所需的 (results, consolidated, platform_annual)。"""
    results = {}
    for p, r in result["platforms"].items():
        results[p] = {
            "mode": r["mode"], "main_view": r["main_view"], "baseline": r["baseline"],
            "unified": pd.DataFrame(r["unified"]),
            "person": pd.DataFrame(r["person"]),
            "field": pd.DataFrame(r["field"]) if r["field"] is not None else None,
            "goods": pd.DataFrame(r["goods"]) if r["goods"] is not None else None,
        }
    return (results,
            pd.DataFrame(result["views"]["consolidated"]),
            pd.DataFrame(result["views"]["platform_annual"]))


def _render_export(root: Path, run: dict, result: dict, fmt: str, dest: Path) -> None:
    """渲染导出产物（写临时文件后由调用方原子落位）。"""
    from .. import report

    snap = load_snapshot(root, run["snapshot_id"])
    if fmt == "json":
        store.write_json(dest, {"run": run, "snapshot": snapshot_summary(snap),
                                "result": result})
        return
    results, consolidated, platform_annual = _rebuild_results(result)
    if fmt == "xlsx":
        plan = load_draft(root, run["plan_id"])
        version = store.read_json(_versions_dir(root, run["plan_id"])
                                  / f"{run['version_key']}.json")
        cfg = {"caliber": {**snap["caliber_frozen"],
                           "baseline_months": plan["caliber"]["baseline_months"],
                           "target_months": plan["period"]["target_months"]},
               "scenarios": {k: v["params"] for k, v in version["content"]["scenarios"].items()},
               "identity": {"plan_id": run["plan_id"], "version": run["version"],
                            "run_id": run["run_id"], "saved": run["saved"],
                            "engine_version": run["engine_version"],
                            "snapshot_id": run["snapshot_id"],
                            "sources": "、".join(dict.fromkeys(s["name"] for s in snap["sources"]))}}
        report.write_report(dest, results, consolidated, platform_annual, cfg,
                            demo=bool(snap.get("synthetic")))
        return
    if fmt == "csv":
        import zipfile
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            for p, r in result["platforms"].items():
                df = pd.DataFrame(r["unified"])
                zf.writestr(f"月度指标_{p}.csv", df.to_csv(index=False))
            zf.writestr("全渠道汇总.csv",
                        pd.DataFrame(result["views"]["consolidated"]).to_csv(index=False))
        return
    raise ValidationError(f"未知导出格式：{fmt}（支持 {('/').join(_EXPORTERS)}）")


def export_run(root: Path, plan_id: str, run_id: str, fmt: str) -> dict:
    """导出指定运行的产物。同格式去重（重试不重新渲染，绝不重新计算）。"""
    if fmt not in _EXPORTERS:
        raise ValidationError(f"未知导出格式：{fmt}（支持 {('/').join(_EXPORTERS)}）")
    run = get_run(root, plan_id, run_id)
    run_dir = _runs_dir(root, plan_id) / run_id
    existing = (run.get("exports") or {}).get(fmt)
    if existing:
        f = run_dir / existing["file"]
        if f.is_file():
            return {"file": str(f), "reused": True, "run_id": run_id, "format": fmt}
    result = get_run_result(root, plan_id, run_id)
    ext = {"xlsx": "xlsx", "csv": "zip", "json": "json"}[fmt]
    name = {"xlsx": "目标测算报告", "csv": "月度指标", "json": "运行快照"}[fmt]
    rel = f"exports/{name}_{run_id}.{ext}"
    dest = run_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.name}.tmp-{os.getpid()}-{time.time_ns()}")
    try:
        _render_export(root, run, result, fmt, tmp)
        os.replace(tmp, dest)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise  # 运行已保存，导出失败可重试（不撤销运行、不重新计算）
    run.setdefault("exports", {})[fmt] = {"file": rel, "created": models.now_iso(),
                                          "renderer": f"{fmt}-1.0"}
    store.write_json(run_dir / "run.json", run)
    return {"file": str(dest), "reused": False, "run_id": run_id, "format": fmt}


# ---------- 示例数据与旧版产物 ----------

def import_synthetic(root: Path, plan_id: str, base_revision: int) -> dict:
    """载入示例数据：内置合成月度指标走正常 import 管道（synthetic 标记全程跟随）。"""
    # 与已批准 demo 同形：天猫/抖音，2026 年 12 个月，基期 720/560 万，新客占比 30%/45%
    shares = [.065, .06, .07, .075, .08, .095, .075, .08, .08, .085, .135, .1]
    platforms = {}
    for name, base_wan, new_share in (("天猫", 720.0, 0.30), ("抖音", 560.0, 0.45)):
        rows = []
        for i, s in enumerate(shares, 1):
            gmv = base_wan * 10000 * s
            new_gmv = gmv * new_share
            rows.append({"月份": f"2026-{i:02d}",
                         "新客数": round(new_gmv / 150), "新客客单": 150.0,
                         "老客数": round((gmv - new_gmv) / (1.5 * 180)),
                         "老客复购频次": 1.5, "老客客单": 180.0})
        platforms[name] = pd.DataFrame(rows)
    return _import_frames(root, plan_id, platforms, base_revision, synthetic=True)


def _import_frames(root: Path, plan_id: str, frames: dict, base_revision: int,
                   synthetic: bool) -> dict:
    """内存 DataFrame（平台→月度指标）经同一校验与快照管道导入。"""
    cfg = _load_config(root) or {}
    frozen = {k: cfg.get("caliber", {}).get(k, v) for k, v in _DEFAULT_INGEST_CALIBER.items()}
    platforms, confirmable = {}, []
    for p, df in frames.items():
        df = ingest_agg.validate_agg_frame(df.copy(), p)
        unified = ingest_agg.to_unified(df, p)
        platforms[p] = {"mode": "B", "mapping": {}, "unified": unified, "structure": None}
    ends = [pd.Period(v["unified"]["month"].max(), freq="M") for v in platforms.values()]
    common_end = max(ends) if ends else None
    meta_platforms = {}
    for p, v in platforms.items():
        cov = pipeline._coverage(v["unified"], common_end)
        meta_platforms[p] = {"mode": "B", "mapping": {},
                             "months": int(len(v["unified"])),
                             "history_start": cov["history_start"], "history_end": cov["history_end"],
                             "coverage": cov}
    content = {"platforms": {p: {"mode": "B", "mapping": {},
                                 "unified": models.frame_records(v["unified"]),
                                 "structure": None} for p, v in platforms.items()},
               "caliber_frozen": frozen,
               "files": [{"name": "内置合成示例", "sha256": "synthetic"}]}
    snapshot_id = f"snap-{models.content_key(content)}"
    snap_dir = store.v2_root(root) / "snapshots" / snapshot_id
    if not snap_dir.is_dir():
        snapshot = {"snapshot_id": snapshot_id, "created": models.now_iso(),
                    "synthetic": True,
                    "sources": [{"kind": "synthetic", "name": "内置合成示例", "platform": p}
                                for p in platforms],
                    "caliber_frozen": frozen, "platforms": meta_platforms,
                    "quality": {"blockers": [], "confirmable": confirmable, "warnings": []},
                    "common_end": str(common_end) if common_end is not None else None}
        store.write_json(snap_dir / "snapshot.json", snapshot)
        for p, v in platforms.items():
            store.write_json(snap_dir / f"unified_{p}.json",
                             models.frame_records(v["unified"]))
    snapshot = store.read_json(snap_dir / "snapshot.json")
    draft = update_draft(root, plan_id, {"data": {"snapshot_id": snapshot_id},
                                         "scope": {"platforms": list(platforms)}},
                         base_revision=base_revision, source="import",
                         description="载入内置合成示例数据")
    return {"draft": draft, "snapshot": snapshot_summary(snapshot)}


def legacy_artifacts(root: Path) -> list:
    """旧版产物清单（workspace/forecast/output）：只读列出，明确未关联新运行。"""
    out = []
    d = Path(root) / "workspace" / "forecast" / "output"
    if not d.is_dir():
        return out
    for f in sorted(d.rglob("*")):
        if f.is_file() and not f.name.startswith((".", "~$")):
            out.append({"name": f.name, "path": str(f.relative_to(d)),
                        "size": f.stat().st_size,
                        "mtime": models.sanitize(f.stat().st_mtime)})
    return out


# ---------- 旧版 assistant_params.json 迁移（差异预览→确认并入，未知字段列明） ----------

def legacy_assistant_params_path(root: Path) -> Path:
    return Path(root) / "workspace" / "forecast" / "assistant_params.json"


def assistant_params_preview(root: Path, plan_id: str) -> dict:
    """旧助手参数 → 当前方案的差异预览（只读；未知情景/字段列明，不静默丢弃）。"""
    f = legacy_assistant_params_path(root)
    if not f.is_file():
        return {"exists": False, "items": [], "unknown_fields": []}
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"exists": True, "error": f"assistant_params.json 无法解析：{e}",
                "items": [], "unknown_fields": []}
    draft = load_draft(root, plan_id)
    known = set(PERSON_KEYS + FIELD_KEYS) | {"tier_growth"}
    items, unknown = [], []
    for sc, params in (raw.get("scenarios") or {}).items():
        if sc not in draft["scenarios"]:
            unknown.append(f"未知情景：{sc}")
            continue
        for k, v in (params or {}).items():
            if k not in known:
                unknown.append(f"{sc}.{k}（未知字段）")
                continue
            old = draft["scenarios"][sc]["params"].get(k)
            if old == v:
                continue  # 同值不产生差异项
            items.append({"scenario": sc, "param": k, "old": old, "new": v})
    return {"exists": True, "items": items, "unknown_fields": unknown}


def import_assistant_params(root: Path, plan_id: str, base_revision: int) -> dict:
    """确认并入旧助手参数：作为一次来源=import 的编辑写入草稿（改动走唯一入口）。

    未知字段只列明不并入；并入后假设确认按域哈希失效（与其他编辑一致）。
    """
    preview = assistant_params_preview(root, plan_id)
    if not preview.get("exists"):
        raise ValidationError("没有可并入的旧助手参数（workspace/forecast/assistant_params.json 不存在）")
    if preview.get("error"):
        raise ValidationError(preview["error"])
    if not preview["items"]:
        return {"draft": load_draft(root, plan_id), "merged": 0,
                "unknown_fields": preview["unknown_fields"]}
    scen_patch: dict = {}
    for it in preview["items"]:
        scen_patch.setdefault(it["scenario"], {"params": {}})["params"][it["param"]] = it["new"]
    draft = update_draft(root, plan_id, {"scenarios": scen_patch},
                         base_revision=base_revision, source="import",
                         description=f"并入旧版助手参数（{len(preview['items'])} 项差异）")
    return {"draft": draft, "merged": len(preview["items"]),
            "unknown_fields": preview["unknown_fields"]}
